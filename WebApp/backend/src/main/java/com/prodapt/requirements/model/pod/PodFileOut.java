package com.prodapt.requirements.model.pod;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class PodFileOut {

    @JsonProperty("id")
    private String id;

    @JsonProperty("filename")
    private String filename;

    @JsonProperty("file_path")
    private String filePath;

    @JsonProperty("storage_location")
    private String storageLocation;

    @JsonProperty("uploaded_by")
    private String uploadedBy;

    @JsonProperty("upload_time")
    private String uploadTime;

    @JsonProperty("status")
    private String status;

    @JsonProperty("file_size")
    private Long fileSize;

    @JsonProperty("mime_type")
    private String mimeType;

    @JsonProperty("coverage_gaps")
    private String coverageGaps;
}
