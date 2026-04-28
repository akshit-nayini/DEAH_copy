"""
services/icd_parser.py
-----------------------
Parses an ICD CSV and extracts structured metadata used to enrich LLM prompts.
Ported and extended from v2 ICDParser — adapted for DEAH header conventions.
"""
from __future__ import annotations
import csv
import io


class ICDParserService:
    COL   = ['column_name', 'col_name', 'name', 'field_name', 'source_column',
             'target_column', 'field', 'column']
    TYPE  = ['data_type', 'type', 'datatype', 'bq_type', 'source_type',
             'target_type', 'dtype', 'col_type']
    NULL  = ['nullable', 'null', 'is_nullable', 'nullability', 'mode', 'required', 'is_null']
    PK    = ['primary_key', 'pk', 'is_pk', 'key', 'constraint', 'constraints', 'is_primary']
    NOTE  = ['notes', 'note', 'pii', 'enum', 'description', 'tags',
             'comment', 'remarks', 'classification']
    LEN   = ['length', 'max_length', 'size', 'max_size', 'char_length', 'varchar_length']
    TABLE = ['table_name', 'table', 'source_table', 'target_table', 'tbl']

    def __init__(self, csv_text: str):
        self.text = csv_text.strip()

    def _idx(self, headers: list[str], names: list[str]) -> int:
        return next((i for i, h in enumerate(headers) if h in names), -1)

    def parse(self) -> dict:
        """
        Returns
        -------
        dict with keys:
            schema_text  : pipe-formatted column lines for prompt injection
            table_name   : str
            col_count    : int
            column_defs  : list of dicts [{name, dtype, nullable, is_pk, note, length}]
            pii_cols     : list[str]
            pk_cols      : list[str]
            enum_cols    : list[str]  — 'col_name: note text'
            error        : str | None
        """
        _empty = dict(schema_text='', table_name='target_table', col_count=0,
                      column_defs=[], pii_cols=[], pk_cols=[], enum_cols=[])

        reader = csv.reader(io.StringIO(self.text))
        rows   = [r for r in reader if any(c.strip() for c in r)]
        if len(rows) < 2:
            return {**_empty, 'error': 'ICD CSV has no data rows.'}

        raw_h = [h.strip().replace('"', '') for h in rows[0]]
        hdrs  = [h.lower() for h in raw_h]

        cI  = self._idx(hdrs, self.COL)
        tI  = self._idx(hdrs, self.TYPE)
        nI  = self._idx(hdrs, self.NULL)
        pI  = self._idx(hdrs, self.PK)
        noI = self._idx(hdrs, self.NOTE)
        lI  = self._idx(hdrs, self.LEN)
        # Prefer target_table over source_table so LLM queries reference the BQ table
        tbI = next((hdrs.index(p) for p in ['target_table', 'table_name', 'table', 'source_table', 'tbl'] if p in hdrs), -1)

        if cI == -1:
            return {**_empty, 'error': f'Missing column_name header. Found: {", ".join(raw_h)}'}

        def cell(row: list, i: int) -> str:
            return row[i].strip().replace('"', '') if 0 <= i < len(row) else ''

        table_name  = ''
        lines:       list[str]  = []
        pii_cols:    list[str]  = []
        enum_cols:   list[str]  = []
        pk_cols:     list[str]  = []
        column_defs: list[dict] = []

        for row in rows[1:]:
            col = cell(row, cI)
            if not col:
                continue
            dtype  = cell(row, tI) or 'STRING'
            n_raw  = cell(row, nI) or 'NULL'
            pk     = cell(row, pI)
            note   = cell(row, noI)
            length = cell(row, lI)

            if tbI >= 0 and not table_name:
                table_name = cell(row, tbI)

            if   n_raw.lower() in ('yes', 'true', '1', 'nullable', 'null'):
                nullable = 'NULL'
            elif n_raw.lower() in ('no', 'false', '0', 'not null', 'not_null', 'required'):
                nullable = 'NOT NULL'
            else:
                nullable = n_raw.upper() or 'NULL'

            is_pk = bool(pk and pk.lower() not in ('', 'false', '0', 'no', 'n'))
            # Also detect PK from notes column (e.g. "Primary Key", "PK")
            if not is_pk and note and any(
                kw in note.lower() for kw in ('primary key', 'primarykey', ' pk', 'pk ')
            ):
                is_pk = True
            con   = 'PRIMARY KEY' if is_pk else ''
            if note:
                con = f'{con} | {note}'.strip(' | ') if con else note

            if is_pk:                   pk_cols.append(col)
            if 'pii'  in note.lower():  pii_cols.append(col)
            if 'enum' in note.lower():  enum_cols.append(f'{col}: {note}')

            sfx = f' [max:{length}]' if length else ''
            lines.append(f'{col:<20}| {dtype:<13}| {nullable:<9}| {con}{sfx}'.rstrip())
            column_defs.append({
                'name':     col,
                'dtype':    dtype,
                'nullable': nullable,
                'is_pk':    is_pk,
                'note':     note,
                'length':   length,
            })

        if not lines:
            return {**_empty, 'error': 'No valid schema rows parsed.'}

        return {
            'schema_text': '\n'.join(lines),
            'table_name':  table_name or 'target_table',
            'col_count':   len(lines),
            'column_defs': column_defs,
            'pii_cols':    pii_cols,
            'enum_cols':   enum_cols,
            'pk_cols':     pk_cols,
            'error':       None,
        }