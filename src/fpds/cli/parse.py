"""
Parsing command for retrieving FPDS federal
contracts

author: derek663@gmail.com
last_updated: 12/30/2022
"""

import asyncio
import json
from pathlib import Path

import click
from click import UsageError

from fpds import fpdsRequest
from fpds.config import FPDS_DATA_DATE_DIR
from fpds.utilities import validate_kwarg


def sanitize_param_value(value: str) -> str:
    """
    Sanitizes a parameter value for use in filenames.

    If the value is in a date range format (e.g., "[2025/02/14,2025/02/14]"),
    this function will remove the brackets, remove slashes, replace the comma
    with a dash, and remove any whitespace.

    For any other value, only alphanumeric characters and a few safe symbols
    (dot, underscore, dash) are allowed.
    """
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]  # remove surrounding brackets
        # Remove slashes and spaces, and replace comma with a dash.
        inner = inner.replace("/", "")
        inner = inner.replace(" ", "")
        inner = inner.replace(",", "-")
        return inner
    else:
        # Allow only alphanumeric characters and . _ -
        return "".join(c for c in value if c.isalnum() or c in "._-")


@click.command()
@click.option("-o", "--output", required=False, help="Output directory")
@click.argument("params", nargs=-1)
def parse(params, output):
    """
    Parsing command for the FPDS Atom feed

    \b
    Usage:
        $ fpds parse [PARAMS] [OPTIONS]

    \b
    Positional Argument(s):
        PARAMS  Search criteria parameters for filtering response

        \b
        Reference the Atom Feed Usage documentation at
        https://www.fpds.gov/wiki/index.php/Atom_Feed_Usage
        to determine available parameters. As an example, if
        a user wants to filter for AWARD contract types, the
        parameter criteria should look like this: 'CONTRACT_TYPE=AWARD'.
        A full CLI command could look like this:

        \b
            fpds parse "LAST_MOD_DATE=[2022/01/01, 2022/05/01]" "AGENCY_CODE=7504"
    """

    # Determine output directory: either user-supplied or the default directory.
    if output:
        output_path = Path(output)
        if not output_path.exists():
            click.echo(f"Creating output directory {output_path.resolve()}")
            output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = FPDS_DATA_DATE_DIR

    # Parse positional parameters into a dictionary.
    if not params:
        raise UsageError("Please provide at least one parameter.")

    params_list = [param.split("=", 1) for param in params]
    for param in params_list:
        if len(param) != 2:
            raise UsageError(f"Parameter '{param}' is not in the format KEY=VALUE")
        name, value = param
        param[1] = validate_kwarg(kwarg=name, string=value)
    params_kwargs = dict(params_list)
    click.echo(f"Params to be used for FPDS search: {params_kwargs}")

    # Instantiate the request (with cli_run=True to skip extra validations).
    request = fpdsRequest(**params_kwargs, cli_run=True)
    click.echo("Retrieving FPDS records from ATOM feed...")

    # Retrieve the FPDS data asynchronously.
    records = asyncio.run(request.data())

    # Create filename based on parameters.
    safe_parts = []
    for key, value in params_kwargs.items():
        safe_value = sanitize_param_value(value)
        safe_parts.append(f"{key}-{safe_value}")
    filename = "__".join(safe_parts)

    # Limit filename length to avoid issues.
    if len(filename) > 200:
        filename = filename[:200] + "_truncated"
    filename += ".json"

    data_file = output_path / filename

    # Write the JSON output to file.
    with open(data_file, "w", encoding="utf-8") as outfile:
        json.dump(records, outfile, ensure_ascii=False, indent=2)

    click.echo(f"{len(records)} records have been saved as JSON at: {data_file}")
