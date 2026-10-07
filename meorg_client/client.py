"""Client object."""

import requests
import hashlib as hl
import os
from typing import Union
from urllib.parse import urljoin, urlencode
from meorg_client.exceptions import RequestException
import meorg_client.constants as mcc
import meorg_client.endpoints as endpoints
import meorg_client.exceptions as mx
import meorg_client.utilities as mu
import meorg_client.parallel as meop
import meorg_client.downloads as med
import mimetypes as mt
from pathlib import Path
from tqdm import tqdm


class Client:
    def __init__(self, email: str = None, password: str = None, dev_mode: bool = False):
        """ME.org Client object.

        Supplying email and password will automatically log in.

        Parameters
        ----------
        base_url : str
            Base URL to API.
        email : str, optional
            Registered email address, by default None
        password : str, optional
            User password, by default None
        dev_mode : bool, optional
            Development mode (uses dev environment), by default False
        """

        # Initialise the mimetypes
        mt.init()

        # Dev mode can be set by the user or from the environment
        if dev_mode or mu.is_dev_mode():
            self.base_url = os.getenv("MEORG_BASE_URL_DEV", None)
        else:
            self.base_url = mcc.MEORG_BASE_URL_PROD

        self.headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
        self.last_response = None

        # Automatically login if credentials are set.
        if email is not None and password is not None:
            self.login(email, password)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        url_path_fields: dict = {},
        url_params: dict = {},
        data: dict = {},
        json: dict = {},
        headers: dict = {},
        files: dict = {},
        return_json=True,
        **kwargs,
    ):
        """Make a request against the API

        Parameters
        ----------
        method : str
            HTTP method.
        endpoint : str
            URL template for the API endpoint.
        url_path_fields : dict, optional
            Fields to interpolate into the URL template, by default {}
        url_params : dict, optional
            Parameters to add at end of URL, by default {}
        data : dict, optional
            Data to send along with the request, by default {}
        json : dict, optional
            JSON data to send along with the request, by default {}
        headers : dict, optional
            Headers to attach to the request (will be combined with client headers), by default {}
        files : dict, optional
            Files payload to attach to request, by default {}
        return_json : bool, optional
            Return a JSON dict object, by default True

        Returns
        -------
        dict or requests.Response
            Dictionary or Request object, depending on context.

        Raises
        ------
        mx.InvalidHTTPMethodException
            Raised when the specified method is invalid.
        RequestException
            Raised when the request fails.
        """

        method = method.upper()

        # Check that the method is allowed.
        if method not in mcc.VALID_METHODS:
            raise mx.InvalidHTTPMethodException(method)

        # Get the function and URL
        func = getattr(requests, method.lower())
        url = self._get_url(endpoint, url_params, **url_path_fields)

        # Assemble the headers
        _headers = self._merge_headers(headers)

        # Attach the user agent
        _headers['user-agent'] = mu.get_user_agent()

        # Make the request, set it as the last response for future use
        self.last_response = func(
            url, data=data, json=json, headers=_headers, files=files, **kwargs
        )

        # Check to see if it was successful
        if self.last_response.status_code not in mcc.HTTP_STATUS_SUCCESS_RANGE:
            raise RequestException(
                self.last_response.status_code, self.last_response.text
            )

        # This is the default
        if return_json:
            return self.last_response.json()

        # For flexibility
        return self.last_response

    def _get_url(self, endpoint: str, url_params: dict = {}, **url_path_fields: dict):
        """Get the well-formed URL for the call.

        Parameters
        ----------
        endpoint : str
            Endpoint to be appended to the base URL.
        url_path_fields : dict, optional
            Fields to interpolate into the URL template
        url_params : dict, optional
            Parameters to add at end of URL, by default {}

        Returns
        -------
        str
            URL.
        """
        # Add endpoint to base URL, interpolating url_path_fields
        url_path = urljoin(self.base_url + "/", endpoint).format(**url_path_fields)
        # Add URL parameters (if any)
        if url_params:
            url_path = f"{url_path}?{urlencode(url_params)}"
        return url_path

    def _merge_headers(self, headers: dict = dict()):
        """Merge additional headers into the client headers (i.e. Auth)

        Parameters
        ----------
        headers : dict, optional
            Additional headers to add to the client headers, by default dict()

        Returns
        -------
        dict
            Merged headers.
        """
        return {**self.headers, **headers}

    def login(self, email: str, password: str):
        """Log the user into ME.org.

        Parameters
        ----------
        email : str
            Registered email address.
        password : str
            Password (will be hashed)

        Raises
        ------
        Exception
            When the login fails.
        """

        # Assemble payload
        login_data = {
            "email": email,
            "password": hl.sha256(password.encode("UTF-8")).hexdigest(),
            "hashed": "true",
        }

        # Call
        response = self._make_request(
            method=mcc.HTTP_POST,
            endpoint=endpoints.LOGIN,
            json=login_data,
            return_json=True,
        )

        # Successful login
        if self.last_response.status_code == 200:
            auth_headers = {
                "X-User-Id": response["data"]["userId"],
                "X-Auth-Token": response["data"]["authToken"],
            }

            self.headers.update(auth_headers)

        # Unsuccessful login (technically this will have already failed)
        else:
            raise RequestException(
                self.last_response.status_code, self.last_response.text
            )

    def logout(self):
        """Log the user out. Likely not necessary, can just let sessions expire."""
        response = self._make_request(
            method=mcc.HTTP_POST, endpoint=endpoints.LOGOUT, return_json=False
        )

        # Clear the headers.
        if response.status_code == 200:
            self.headers.pop("X-User-Id", None)
            self.headers.pop("X-Auth-Token", None)

    def get_experiment_dataset_manifest(self, experiment_id: str) -> dict:
        """Get the dataset files of an experiment, with signed download URLs.

        Parameters
        ----------
        experiment_id : str
            Experiment ID.

        Returns
        -------
        dict
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_GET,
            endpoint=endpoints.EXPERIMENT_DATASET_MANIFEST,
            url_path_fields=dict(id=experiment_id),
        )

    def download_experiment_datasets(
        self,
        experiment_id: str,
        output_dir: Union[str, Path],
        n: int = 4,
        progress: bool = True,
    ) -> list:
        """Download the dataset files of an experiment.

        Each file goes to its relativePath under output_dir. A file that is
        already there with the right size is not downloaded again.

        Parameters
        ----------
        experiment_id : str
            Experiment ID.
        output_dir : Union[str, Path]
            Directory for the files.
        n : int, optional
            Number of threads, by default 4.
        progress : bool, optional
            Show a progress bar, by default True.

        Returns
        -------
        list
            Local paths of the files.
        """
        manifest = self.get_experiment_dataset_manifest(experiment_id)
        jobs = [
            (f["url"], med.safe_join(output_dir, f["relativePath"]), f["size"])
            for f in manifest["files"]
        ]
        med.download_files(jobs, n=n, progress=progress)
        return [target for _, target, _ in jobs]

    def _upload_files_parallel(
        self,
        files: Union[str, Path, list],
        id: str,
        n: int = 2,
        progress=True,
    ):
        """Upload files in parallel.

        Parameters
        ----------
        files : Union[str, Path, list]
            A path to a file, or a list of paths.
        id : str
            Module output id to attach to, by default None.
        n : int, optional
            Number of threads to use, by default 2.

        Returns
        -------
        list
            List of dicts or response objects from upload_files.
        """

        # Ensure the object is actually iterable
        files = mu.ensure_list(files)

        # Do the parallel upload
        responses = None
        responses = meop.parallelise(
            self._upload_file, n, filepath=files, id=id, progress=progress
        )

        # These should already be a list as per the parallelise function.
        return responses

    def upload_files(
        self,
        files: Union[str, Path, list],
        id: str,
        n: int = 1,
        progress=True,
    ) -> list:
        """Upload files.

        Parameters
        ----------
        files : Union[str, Path, list]
            A filepath, or a list of filepaths.
        id : str
            Model output ID to immediately attach to.
        n : int, optional
            Number of threads to parallelise over, by default 1


        Returns
        -------
        list
            List of dicts
        """

        # Ensure the files are actually a list
        files = mu.ensure_list(files)

        # Just because someone will try to assign 0 threads...
        if n >= 1 == False:
            raise ValueError("Number of threads must be greater than or equal to 1.")

        # Sequential upload
        responses = list()
        if n == 1:
            for fp in tqdm(files, total=len(files)):
                response = self._upload_file(fp, id=id)
                responses += response
        else:
            responses += self._upload_files_parallel(
                files, n=n, id=id, progress=progress
            )

        # return mu.ensure_list(responses)
        return responses

    def _upload_file(
        self, filepath: Union[str, Path], id: str
    ) -> Union[dict, requests.Response]:
        """Upload a single file.

        Parameters
        ----------
        filepath : path-like
            Path to the file
        id : str
            model_output_id to attach the files to

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.

        Raises
        ------
        TypeError
            When supplied file is neither path-like nor readable.
        FileNotFoundError
            When supplied file cannot be found.
        """

        file_obj = None

        if isinstance(filepath, (str, Path)) and os.path.isfile(filepath):
            file_obj = open(filepath, "rb")

        # Bail out
        else:
            dtype = type(file_obj)
            raise TypeError(f"File is neither path-like nor readable ({dtype}).")

        # Prepare the payload from the files
        payload = list()

        filename = os.path.basename(file_obj.name)
        ext = filename.split(".")[-1]
        mimetype = mt.types_map[f".{ext}"]
        payload.append(("file", (filename, file_obj, mimetype)))

        # Make the request
        response = self._make_request(
            method=mcc.HTTP_POST,
            endpoint=endpoints.FILE_UPLOAD,
            files=payload,
            url_path_fields=dict(id=id),
            return_json=True,
        )

        # Close all the file descriptors (requests should do this, but just to be sure)
        for fd in payload:
            fd[1][1].close()

        return mu.ensure_list(response)

    def list_files(self, id: str) -> Union[dict, requests.Response]:
        """Get a list of model outputs.

        Parameters
        ----------
        id : str
            Model output ID

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_GET,
            endpoint=endpoints.FILE_LIST,
            url_path_fields=dict(id=id),
        )

    def delete_file_from_model_output(self, id: str, file_id: str):
        """Delete file from model output

        Parameters
        ----------
        id : str
            Model output ID.
        file_id : str
            File ID.

        Returns
        -------
        Union[dict, requests.Request]
            Response from ME.org
        """
        return self._make_request(
            method=mcc.HTTP_DELETE,
            endpoint=endpoints.FILE_DELETE,
            url_path_fields=dict(id=id, fileId=file_id),
        )

    def delete_all_files_from_model_output(self, id: str):
        """Delete file from model output

        Parameters
        ----------
        id : str
            Model output ID.

        Returns
        -------
        Union[dict, requests.Request]
            Response from ME.org
        """

        # Get a list of the files currently on the model output
        files = self.list_files(id)
        file_ids = [f.get("id") for f in files.get("data").get("files")]

        responses = list()

        # Do the delete one at a time
        for file_id in file_ids:
            response = self.delete_file_from_model_output(id=id, file_id=file_id)
            responses.append(response)

        return responses

    def start_analysis(
        self, model_output_id: str, experiment_id: str
    ) -> Union[dict, requests.Response]:
        """Start the analysis chain.

        Parameters
        ----------
        id : str
            Model output ID.

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_PUT,
            endpoint=endpoints.ANALYSIS_START,
            url_path_fields=dict(id=model_output_id, expid=experiment_id),
        )

    def model_output_create(
        self, mod_prof_id: str, name: str, **config_params
    ) -> Union[dict, requests.Response]:
        """
        Create a new model output entity
        Parameters
        ----------
        mod_prof_id : str
            Model Profile ID
        exp_id : str
            Experiment ID
        name : str
            Name of Model Output

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_POST,
            endpoint=endpoints.MODEL_OUTPUT_CREATE,
            json=dict(model=mod_prof_id, name=name) | config_params,
        )

    def model_output_query(self, model_id: str = None, name: bool = None) -> Union[dict, requests.Response]:
        """
        Get details for a specific new model output entity
        Parameters
        ----------
        model_id : str
            Model Output ID

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_GET,
            endpoint=endpoints.MODEL_OUTPUT_QUERY,
            url_params=dict(name=name) if name else dict(id=model_id),
        )

    def model_output_update(
        self, model_id: str, updated_fields: dict
    ) -> Union[dict, requests.Response]:
        """
        Update specific fields of an existing model output.
        Parameters
        ----------
        model_id : str
            Model Output ID

        params : dict
            Request body containing necessary fields to be updated

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_PATCH,
            endpoint=endpoints.MODEL_OUTPUT_UPDATE,
            url_path_fields=dict(id=model_id),
            json=updated_fields,
        )

    def model_output_benchmarks_list(
        self, model_id: str, exp_id: str
    ) -> Union[dict, requests.Response]:
        return self._make_request(
            method=mcc.HTTP_GET,
            endpoint=endpoints.MODEL_OUTPUT_BENCHMARKS,
            url_path_fields=dict(id=model_id, expId=exp_id),
        )

    def model_output_benchmarks_replace(
        self, model_id: str, exp_id: str, updated_benchmarks: list[str]
    ) -> Union[dict, requests.Response]:
        """
        Replace benchmarks.
        Parameters
        ----------
        model_id : str
            Model Output ID

        exp_id: str
            Experiment ID

        updated_benchmarks:

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_PATCH,
            endpoint=endpoints.MODEL_OUTPUT_BENCHMARKS,
            url_path_fields=dict(id=model_id, expId=exp_id),
            json=dict(benchmarks=updated_benchmarks),
        )

    def model_output_experiments_extend(
        self, model_id: str, updated_experiments: list[str]
    ) -> Union[dict, requests.Response]:
        """
        Add experiments.
        Parameters
        ----------
        model_id : str
            Model Output ID

        exp_id: str
            Experiment ID

        updated_benchmarks:

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_PATCH,
            endpoint=endpoints.MODEL_OUTPUT_EXPERIMENTS,
            url_path_fields=dict(id=model_id),
            json=dict(experiments=updated_experiments),
        )

    def model_output_experiment_delete(
        self, model_id: str, exp_id: str
    ) -> Union[dict, requests.Response]:
        return self._make_request(
            method=mcc.HTTP_DELETE,
            endpoint=endpoints.MODEL_OUTPUT_EXPERIMENTS,
            url_path_fields=dict(id=model_id),
            json=dict(experiment=exp_id),
        )

    def model_output_delete(self, model_id: str) -> Union[dict, requests.Response]:
        """
        Remove specific new model output entity
        Parameters
        ----------
        model_id : str
            Model Output ID

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_DELETE,
            endpoint=endpoints.MODEL_OUTPUT_DELETE,
            url_path_fields=dict(id=model_id),
        )

    def get_analysis_status(self, id: str) -> Union[dict, requests.Response]:
        """Check the status of the analysis chain.

        Parameters
        ----------
        id : str
            Analysis ID.

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(
            method=mcc.HTTP_GET,
            endpoint=endpoints.ANALYSIS_STATUS,
            url_path_fields=dict(id=id),
        )

    def list_endpoints(self) -> Union[dict, requests.Response]:
        """List the endpoints available to the user.

        Paths are available at .get('paths').keys()

        Returns
        -------
        Union[dict, requests.Response]
            Response from ME.org.
        """
        return self._make_request(method=mcc.HTTP_GET, endpoint=endpoints.ENDPOINT_LIST)

    def success(self) -> bool:
        """Test if the last request was successful.

        Returns
        -------
        bool
            True if successful, False otherwise.
        """
        return self.last_response.status_code in mcc.HTTP_STATUS_SUCCESS_RANGE

    def is_initialised(self, dev: bool = False) -> bool:
        """Check if the client is initialised.
        NOTE: This does not check the login actually works.
        Parameters
        ----------
        dev : bool, optional
            Use dev credentials, by default False
        Returns
        -------
        bool
            True if initialised, False otherwise.
        """
        cred_filename = "credentials.json" if not dev else "credentials-dev.json"
        cred_filepath = mu.get_user_data_filepath(cred_filename)
        return cred_filepath.exists()
