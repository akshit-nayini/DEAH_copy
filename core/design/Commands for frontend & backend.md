# Running Frontend & Backend on the VM

## Ports

| Service | Port |
|---|---|
| FastAPI (backend) | `9190` |
| Streamlit (frontend) | `9200` |

---

## Step 1 — Check if tmux is installed

```bash
tmux -V
```

If not installed:

```bash
sudo apt-get install tmux
```

---

## Step 2 — Create a new tmux session

```bash
tmux new -s deah
```

This opens a new terminal inside tmux named `deah`.

---

## Step 3 — Window 1: Start the FastAPI backend

Inside the tmux session (you are already in Window 1):

```bash
source ~/venv/bin/activate
cd ~/DEAH/core/design/api
uvicorn main:app --host 0.0.0.0 --port 9190
```

You should see:

```
Uvicorn running on http://0.0.0.0:9190
```

---

## Step 4 — Open a second pane in the same session

Press `Ctrl+b` then `Shift+"` — this splits the terminal horizontally, creating a new pane below.

To switch between panes use `Ctrl+b` then arrow keys (Up/Down).

---

## Step 5 — Window 2: Start the Streamlit frontend

```bash
source ~/venv/bin/activate
cd ~/DEAH/core/design/frontend
streamlit run app.py --server.port 9200 --server.address 0.0.0.0
```

You should see:

```
Network URL: http://35.209.107.68:9200
```

We can use this URL in our browser to see the frontend and give inputs.

---

## Step 6 — Detach and leave both running

Press `Ctrl+b` then `d` — detaches from tmux. Both processes keep running in the background even after you close SSH.

---

| Service | URL |
|---|---|
| Streamlit UI | `http://35.209.107.68:9200` |
| FastAPI Swagger docs | `http://35.209.107.68:9190/docs` |

---

## Reconnect later

```bash
tmux attach -t deah
```

---

## Useful tmux commands

| Action | Keys / Command |
|---|---|
| Detach (leave running) | `Ctrl+b` then `d` |
| Reattach | `tmux attach -t deah` |
| Split pane horizontally | `Ctrl+b` then `Shift+"` |
| Switch between panes | `Ctrl+b` then arrow keys (Up/Down) |
| Close current pane | `Ctrl+b` then `x` → confirm `y` |
| List sessions | `tmux ls` |
| Kill session | `tmux kill-session -t deah` |
