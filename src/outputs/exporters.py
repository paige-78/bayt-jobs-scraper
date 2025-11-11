import csv
import json
import logging
from pathlib import Path
from typing import Iterable, List, Mapping

from xml.etree.ElementTree import Element, SubElement, ElementTree

from extractors.utils import ensure_directory, get_logger

SUPPORTED_FORMATS = {"json", "jsonl", "csv", "excel", "xml", "html"}

def export_jobs(
    jobs: Iterable[Mapping[str, object]], output_path: Path, fmt: str, logger: logging.Logger | None = None
) -> Path:
    """
    Export job listings to the given format.

    :param jobs: Iterable of job dictionaries.
    :param output_path: Path where the file should be written.
    :param fmt: One of 'json', 'jsonl', 'csv', 'excel', 'xml', 'html'.
    :return: The output path.
    """
    log = logger or get_logger("export_jobs")
    fmt = fmt.lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported export format '{fmt}'. Supported: {sorted(SUPPORTED_FORMATS)}")

    ensure_directory(output_path.parent)

    job_list: List[Mapping[str, object]] = list(jobs)
    log.info("Exporting %s jobs to %s (%s)", len(job_list), output_path, fmt)

    if fmt == "json":
        _export_json(job_list, output_path, log)
    elif fmt == "jsonl":
        _export_jsonl(job_list, output_path, log)
    elif fmt == "csv":
        _export_csv(job_list, output_path, log)
    elif fmt == "excel":
        _export_excel(job_list, output_path, log)
    elif fmt == "xml":
        _export_xml(job_list, output_path, log)
    elif fmt == "html":
        _export_html(job_list, output_path, log)

    log.info("Export completed: %s", output_path)
    return output_path

def _export_json(jobs: List[Mapping[str, object]], output_path: Path, logger: logging.Logger) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

def _export_jsonl(jobs: List[Mapping[str, object]], output_path: Path, logger: logging.Logger) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")

def _export_csv(jobs: List[Mapping[str, object]], output_path: Path, logger: logging.Logger) -> None:
    if not jobs:
        logger.warning("No jobs to export; writing empty CSV with no headers.")
        output_path.write_text("", encoding="utf-8")
        return

    fieldnames = sorted({key for job in jobs for key in job.keys()})
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs:
            writer.writerow(job)

def _export_excel(jobs: List[Mapping[str, object]], output_path: Path, logger: logging.Logger) -> None:
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:
        logger.error("pandas is required for Excel export. Please install it. Error: %s", exc)
        raise

    df = pd.DataFrame(jobs)
    df.to_excel(output_path, index=False)

def _export_xml(jobs: List[Mapping[str, object]], output_path: Path, logger: logging.Logger) -> None:
    root = Element("jobs")
    for job in jobs:
        job_el = SubElement(root, "job")
        for key, value in job.items():
            field_el = SubElement(job_el, key)
            field_el.text = "" if value is None else str(value)

    tree = ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

def _export_html(jobs: List[Mapping[str, object]], output_path: Path, logger: logging.Logger) -> None:
    if not jobs:
        html_content = "<html><body><p>No jobs found.</p></body></html>"
        output_path.write_text(html_content, encoding="utf-8")
        return

    fieldnames = sorted({key for job in jobs for key in job.keys()})

    rows = []
    # Header
    header_cells = "".join(f"<th>{field}</th>" for field in fieldnames)
    rows.append(f"<tr>{header_cells}</tr>")
    # Data
    for job in jobs:
        cells = "".join(f"<td>{job.get(field, '')}</td>" for field in fieldnames)
        rows.append(f"<tr>{cells}</tr>")

    table_html = "<table border='1'>\n" + "\n".join(rows) + "\n</table>"
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Bayt Job Listings</title>
</head>
<body>
  <h1>Bayt Job Listings</h1>
  {table_html}
</body>
</html>
"""
    output_path.write_text(html_content, encoding="utf-8")