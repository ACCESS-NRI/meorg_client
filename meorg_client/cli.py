"""Command Line Interface"""

import click
from meorg_client.client import Client
import meorg_client.utilities as mcu
import meorg_client.constants as mcc
from meorg_client import __version__
import json
import os
import sys
import getpass
from pathlib import Path
import json


def _get_client() -> Client:
    """Get an authenticated client.

    Returns
    -------
    meorg_client.client.Client
        Client object.
    """
    # Get the dev-mode flag from the environment, better than passing the dev flag everywhere.

    credentials = mcu.get_user_data_filepath("credentials.json")
    credentials_dev = mcu.get_user_data_filepath("credentials-dev.json")

    # In dev mode and the configuration file exists
    if mcu.is_dev_mode() and credentials_dev.is_file():
        credentials = mcu.load_user_data("credentials-dev.json")

    # In dev mode and it doesn't (i.e. Actions)
    elif mcu.is_dev_mode() and not credentials_dev.is_file():
        credentials = dict(
            email=os.getenv("MEORG_EMAIL"), password=os.getenv("MEORG_PASSWORD")
        )

    # Production credentials
    else:
        credentials = mcu.load_user_data("credentials.json")

    # Get the client
    return Client(
        email=credentials["email"],
        password=credentials["password"],
        dev_mode=mcu.is_dev_mode(),
    )


def _call(func: callable, **kwargs) -> dict:
    """Simple wrapper to handle exceptions.

    Exceptions are captured broadly and raw error message printed before non-zero exit.

    Parameters
    ----------
    func : callable
        Method to call.
    **kwargs :
        Additional arguments to method.

    Returns
    -------
    dict
        Response dictionary.
    """
    try:
        return func(**kwargs)
    except Exception as ex:
        click.echo(getattr(ex, "msg", str(ex)), err=True)

        # Bubble up the exception
        if mcu.is_dev_mode():
            raise

        sys.exit(1)


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option(version=__version__)
def cli():
    """
    ModelEvaluation.org client utility.

    For more detail run:
    meorg [SUBCOMMAND] --help
    """
    pass


@click.command("list")
def list_endpoints():
    """
    List the available endpoints for the server.
    """
    client = _get_client()
    endpoints = _call(client.list_endpoints)

    for url, config in endpoints.get("paths").items():
        for method in config.keys():
            out = " ".join(
                [
                    method.upper(),
                    url,
                    endpoints.get("paths")[url][method]["description"],
                ]
            )

            click.echo(out)


@click.command("upload")
@click.argument("file_path", nargs=-1)
@click.argument("id")
@click.option("-n", default=1, help="Number of threads for parallel uploads.")
def file_upload(file_path, id, n: int = 1):
    """
    Upload a file to the server.

    Prints Job ID on success, which is used by file-status to check transfer status.

    If attach_to is used then no ID is returned.
    """
    client = _get_client()

    # Upload the file, get the job ID
    responses = _call(
        client.upload_files,
        files=list(file_path),
        n=n,
        id=id,
        progress=True,
    )

    for response in responses:

        files = response.get("data").get("files")
        for f in files:
            click.echo(f.get("id"))


@click.command("list")
@click.argument("id")
def file_list(id: str):
    """
    List the files currently attached to a model output.

    Prints 1 File ID per line.
    """
    client = _get_client()
    response = _call(client.list_files, id=id)

    for f in response.get("data").get("files"):
        click.echo(f)


@click.command("attach")
@click.argument("file_id")
@click.argument("output_id")
def file_attach(file_id: str, output_id: str):
    """
    Attach a file to a model output.
    """
    client = _get_client()

    _ = _call(client.attach_files_to_model_output, id=output_id, files=[file_id])

    click.echo("SUCCESS")


@click.command("delete_all")
@click.argument("output_id")
def file_delete_all(output_id: str):
    """Detach all files from a model output.

    Parameters
    ----------
    output_id : str
        Model output ID.
    """
    client = _get_client()
    _ = _call(client.delete_all_files_from_model_output, id=output_id)
    click.echo("SUCCESS")


@click.command("delete")
@click.argument("output_id")
@click.argument("file_id")
def file_delete(output_id: str, file_id: str):
    """Detach a file from a model output.

    Parameters
    ----------
    output_id : str
        Model output ID.
    """
    client = _get_client()
    _ = _call(client.delete_file_from_model_output, id=output_id, file_id=file_id)
    click.echo("SUCCESS")


@click.command("start")
@click.argument("model_output_id")
@click.argument("experiment_id")
def analysis_start(model_output_id: str, experiment_id: str):
    """
    Start the analysis for the model output id, and an associated experiment ID.

    Prints the Analysis ID, which can be used in analysis-status.
    """
    client = _get_client()

    response = _call(
        client.start_analysis,
        model_output_id=model_output_id,
        experiment_id=experiment_id,
    )

    if client.success():
        analysis_id = response.get("data").get("analysisId")
        click.echo(analysis_id)


def _generate_model_output_config(
    state_selection: str, parameter_selection: str, comments: str, is_bundle: bool
):
    state_sel_dict = {
        "default": "default model initialisation",
        "spinup": "model spinup on forcing data",
        "measurements": "states derived directly from measurements",
        "other": "other",
    }

    param_sel_dict = {
        "automated": "automated calibration",
        "manual": "manual calibration",
        "none": "no calibration (model default values)",
    }

    config_params = {
        "state_selection": state_sel_dict.get(state_selection),
        "parameter_selection": param_sel_dict.get(parameter_selection),
        "comments": comments,
        "is_bundle": is_bundle,
    }
    config_params = {k: v for k, v in config_params.items() if v}

    return config_params


@click.command("create")
@click.argument("mod_prof_id")
@click.argument("name")
@click.option(
    "--state-selection",
    type=click.Choice(["default", "spinup", "measurements", "other"]),
    help="",
)
@click.option(
    "--parameter-selection",
    type=click.Choice(["automated", "manual", "none"]),
    help="",
)
@click.option(
    "--comments",
    type=str,
    help="",
)
@click.option(
    "--is-bundle",
    is_flag=True,
    default=False,
    help="",
)
def create_new_model_output(
    mod_prof_id: str,
    name: str,
    state_selection: str,
    parameter_selection: str,
    comments: str,
    is_bundle: bool,
):
    """
    Create a new model output profile.

    Parameters
    ----------
    mod_prof_id : str
        Model profile ID.

    exp_id : str
        Experiment ID.

    name : str
        New model output name

    state_selection : str
        Maps to one of "default model initialisation", "model spinup on forcing data",
        "states derived directly from measurements", or "other"
    parameter_selection : str
        Maps to one of "automated calibration", "manual calibration", or
        "no calibration (model default values)"
    comments : str
        Additional Info on Model output
    is_bundle : bool
        Indicates if the model output is a bundle
    Prints modeloutput ID of created object, and whether it already existed or not.
    """
    client = _get_client()
    config_params = _generate_model_output_config(
        state_selection, parameter_selection, comments, is_bundle
    )
    response = _call(
        client.model_output_create, mod_prof_id=mod_prof_id, name=name, **config_params
    )

    if client.success():
        model_output_id = response.get("data").get("modeloutput")
        existing = response.get("data").get("existing")
        click.echo(f"Model Output ID: {model_output_id}")
        if existing is not None:
            click.echo("Warning: Overwriting existing model output ID")
    return model_output_id


@click.command("query", no_args_is_help=True)
@click.option("--name", required=False, help="Name of model output entity.")
@click.argument("model_id", required=False)
def model_output_query(model_id: str, name: str):
    """
    Get details for a specific new model output entity

    Parameters
    ----------
    model_id : str
        Model Output ID.
    name : str
        Name of model output entity.

    Prints the `id` modeloutput, and JSON representation for the remaining metadata if in dev mode.
    """
    client = _get_client()

    if name:
        response = _call(client.model_output_query, name=name)
    else:
        response = _call(client.model_output_query, model_id=model_id)

    if client.success():

        model_output_id = response.get("data").get("modeloutput").get("id")
        click.echo(model_output_id)


def _parse_csv(ctx, param, value):
    if not value:
        return []

    return value.split(",")


@click.command("update")
@click.argument("model_output_id")
@click.option(
    "--name",
    type=str,
    help="",
)
@click.option(
    "--model-profile-id",
    type=str,
    help="",
)
@click.option(
    "--state-selection",
    type=click.Choice(["default", "spinup", "measurements", "other"]),
    help="",
)
@click.option(
    "--parameter-selection",
    type=click.Choice(["automated", "manual", "none"]),
    help="",
)
@click.option(
    "--comments",
    type=str,
    help="",
)
@click.option(
    "--is-bundle",
    is_flag=True,
    default=False,
    help="",
)
def model_output_update(
    model_output_id: str,
    name: str,
    model_profile_id: str,
    state_selection: str,
    parameter_selection: str,
    comments: str,
    is_bundle: bool,
):
    """

    Update specific fields of an existing model output.

    Parameters
    ----------
    model_output_id : str
        Model Output ID
    name : str
        Model Output Name
    model_profile_id : str
        Model Profile ID
    state_selection : str
        Maps to one of "default model initialisation", "model spinup on forcing data",
        "states derived directly from measurements", or "other"
    parameter_selection : str
        Maps to one of "automated calibration", "manual calibration", or
        "no calibration (model default values)"
    comments : str
        Additional Info on Model output
    is_bundle : bool
        Indicates if the model output is a bundle
    """
    client = _get_client()

    updated_fields = {
        "name": name,
        "model": model_profile_id,
    } | _generate_model_output_config(
        state_selection, parameter_selection, comments, is_bundle
    )

    # Remove unpassed params to CLI
    updated_fields = {k: v for k, v in updated_fields.items() if v}

    _ = _call(
        client.model_output_update,
        model_id=model_output_id,
        updated_fields=updated_fields,
    )

    if client.success():
        click.echo("Parameters of MO updated")


@click.command("list")
@click.argument("model_output_id")
@click.argument("exp_id")
def model_output_benchmarks_list(model_output_id: str, exp_id: str):
    """List model benchmarks.

    Parameters
    ----------
    model_output_id : str
        Model output ID
    exp_id : str
        Experiment ID
    """
    client = _get_client()
    response = _call(
        client.model_output_benchmarks_list,
        model_id=model_output_id,
        exp_id=exp_id,
    )

    if client.success():
        click.echo(
            f"List of available benchmarks: {json.dumps(response.get('data').get('benchmarks'), indent=4)}"
        )
        click.echo(
            f"List of linked benchmarks: {json.dumps(response.get('data').get('current'), indent=4)}"
        )

        return response.get("data")


@click.command("update")
@click.argument("model_output_id")
@click.argument("exp_id")
@click.argument("benchmark_ids", default="", callback=_parse_csv)
def model_output_benchmarks_replace(
    model_output_id: str, exp_id: str, benchmark_ids: str
):
    """
    Change benchmarks associated with Model output and Experiment.

    Parameters
    ----------
    model_output_id : str
        Model output ID
    exp_id : str
        Experiment ID
    benchmarks : list[str]
        List of benchmarks IDs to fully replace existing
    """
    client = _get_client()
    _ = _call(
        client.model_output_benchmarks_replace,
        model_id=model_output_id,
        exp_id=exp_id,
        updated_benchmarks=benchmark_ids,
    )

    if client.success():
        click.echo("Benchmark updated")


@click.command("update")
@click.argument("model_output_id")
@click.argument("exp_ids", default="", callback=_parse_csv)
def model_output_experiments_extend(model_output_id: str, exp_ids: list[str]):
    """
    Extend existing set of experiment associations.

    Parameters
    ----------
    model_output_id : str
        Model output ID

    experiments : list[str]
        List of experiment IDs
    """
    client = _get_client()
    _ = _call(
        client.model_output_experiments_extend,
        model_id=model_output_id,
        updated_experiments=exp_ids,
    )

    if client.success():
        click.echo("Experiments updated")


@click.command("delete")
@click.argument("model_output_id")
@click.argument("exp_id")
def model_output_experiment_delete(model_output_id: str, exp_id: str):
    """Delete specific experiment associated with model output

    Parameters
    ----------
    model_output_id : str
        Model output ID

    experiment : str
        Experiment IDs
    """
    client = _get_client()
    _ = _call(
        client.model_output_experiment_delete, model_id=model_output_id, exp_id=exp_id
    )

    if client.success():
        click.echo(f"Experiment ID: {exp_id} deleted")


@click.command("delete")
@click.argument("model_id")
def model_output_delete(model_id: str):
    """
    Remove model output entity

    Parameters
    ----------
    model_id : str
        Model Output ID.

    Prints the status of the operation.
    """
    client = _get_client()

    response = _call(client.model_output_delete, model_id=model_id)

    if client.success():
        if mcu.is_dev_mode():
            click.echo(f"Delete: {json.dumps(response, indent=4)}")
        else:
            click.echo(f"Operation status: {response.get('status')}")


@click.command("status")
@click.argument("id")
def analysis_status(id: str):
    """
    Get the status of the analysis.

    Prints the status of the analysis and the URL to the dashboard.
    """
    client = _get_client()
    response = _call(client.get_analysis_status, id=id)
    status = response.get("status")

    # Error case
    if status == "error":
        click.echo(response.get("message"), err=True)
        sys.exit(1)

    # Get the status out of the data object
    status = response.get("data").get("status")
    url = response.get("data").get("url")

    click.echo(status)
    click.echo(url)


@click.command("download")
@click.argument("experiment_id")
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Directory for the dataset files.",
)
@click.option("-n", default=4, show_default=True, help="Number of threads.")
def dataset_download(experiment_id: str, output_dir: Path, n: int):
    """
    Download the dataset files of an experiment.

    Prints the path of each file. Files that are already complete are kept.
    """
    client = _get_client()
    paths = _call(
        client.download_experiment_datasets,
        experiment_id=experiment_id,
        output_dir=output_dir,
        n=n,
    )

    for path in paths:
        click.echo(path)


@click.command()
@click.option(
    "--dev", is_flag=True, default=False, help="Setup for the development server."
)
def initialise(dev: bool = False):
    """
    Initialise the client on the system.
    """
    email = input("Enter your email for modelevaluation.org: ")
    password = getpass.getpass("Enter your password for modelevaluation.org: ")

    click.echo("Testing connection...")
    client = Client(dev_mode=dev)

    try:
        client.login(email, password)
    except Exception as ex:
        click.echo("Unable to establish connection to server.", err=True)
        click.echo(ex.msg, err=True)
        sys.exit(1)

    click.echo("Connection established.")

    # Build out the dictionary and save it to the user home.
    credentials = dict(email=email, password=password)

    filename = "credentials.json" if not dev else "credentials-dev.json"

    cred_dir = Path.home() / ".meorg"
    cred_dir.mkdir(parents=True, exist_ok=True)
    cred_filepath = cred_dir / filename
    json.dump(credentials, open(cred_filepath, "w"), indent=4)

    click.echo("Credentials written to " + str(cred_filepath))


# Add groups for nested subcommands
@click.group("endpoints", help="API endpoint commands.")
def cli_endpoints():
    pass


@click.group("file", help="File commands.")
def cli_file():
    pass


@click.group("analysis", help="Analysis commands.")
def cli_analysis():
    pass


@click.group("output", help="Model output commands.")
def cli_model_output():
    pass


@click.group("benchmark", help="Model output benchmark commands.")
def cli_model_benchmark():
    pass


@click.group("experiment", help="Model output experiment commands.")
def cli_model_experiments():
    pass


@click.group("dataset", help="Experiment dataset commands.")
def cli_dataset():
    pass


# Add file commands
cli_file.add_command(file_list)
cli_file.add_command(file_upload)
cli_file.add_command(file_delete)
cli_file.add_command(file_delete_all)

# Add endpoint commands
cli_endpoints.add_command(list_endpoints)

# Add analysis commands
cli_analysis.add_command(analysis_start)
cli_analysis.add_command(analysis_status)

# Add output command
cli_model_output.add_command(create_new_model_output)
cli_model_output.add_command(model_output_query)
cli_model_output.add_command(model_output_update)
cli_model_output.add_command(model_output_delete)

# Benchmarks command
cli_model_benchmark.add_command(model_output_benchmarks_list)
cli_model_benchmark.add_command(model_output_benchmarks_replace)

# Experiments command
cli_model_experiments.add_command(model_output_experiments_extend)
cli_model_experiments.add_command(model_output_experiment_delete)

# Dataset commands
cli_dataset.add_command(dataset_download)

# Add subparsers to the master
cli.add_command(cli_endpoints)
cli.add_command(cli_file)
cli.add_command(cli_analysis)
cli.add_command(initialise)
cli.add_command(cli_model_output)
cli.add_command(cli_model_benchmark)
cli.add_command(cli_model_experiments)
cli.add_command(cli_dataset)


if __name__ == "__main__":
    cli()
