"""API Endpoints."""

# List of endpoints (specification)
ENDPOINT_LIST = "openapi.json"

# Authentication
LOGIN = "login"
LOGOUT = "logout"

# Files
FILE_LIST = "modeloutput/{id}/files"
FILE_UPLOAD = FILE_LIST
FILE_DELETE = "modeloutput/{id}/files/{fileId}"
FILE_STATUS = "files/status/{id}"

# Analysis
ANALYSIS_START = "modeloutput/{id}/{expid}/start"
ANALYSIS_STATUS = "analysis/{id}/status"

# Experiments
EXPERIMENT_DATASET_MANIFEST = "experiment/{id}/datasets/manifest"

# Model Outputs
MODEL_OUTPUT_CREATE = "modeloutput"
MODEL_OUTPUT_QUERY = MODEL_OUTPUT_CREATE

MODEL_OUTPUT_UPDATE = "modeloutput/{id}"
MODEL_OUTPUT_DELETE = MODEL_OUTPUT_UPDATE

MODEL_OUTPUT_BENCHMARKS = "modeloutput/{id}/{expId}/available-benchmarks"
MODEL_OUTPUT_EXPERIMENTS = "modeloutput/{id}/available-experiments"
