package com.prodapt.development.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GoogleDriveSourceDetails {

    @NotBlank
    @JsonProperty("drive_url_or_id")
    private String driveUrlOrId;

    @NotBlank
    @JsonProperty("oauth_token")
    private String oauthToken;
}
