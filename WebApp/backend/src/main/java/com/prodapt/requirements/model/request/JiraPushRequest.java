package com.prodapt.requirements.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
public class JiraPushRequest {

    @JsonProperty("task_ids")
    private List<String> taskIds;
}
