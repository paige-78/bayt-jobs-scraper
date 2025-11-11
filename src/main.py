import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from extractors.bayt_parser import BaytJobScraper
from extractors.utils import HttpSettings, get_logger, load_json_file, setup_logging
from outputs.exporters import export_jobs

def resolve_paths() -> Dict[str, Path]:
    """
    Resolve important project paths relative to this file.
    """
    src_dir = Path(__file__).resolve().parent
    project_root = src_dir.parent
    return {
        "src_dir": src_dir,
        "project_root": project_root,
        "settings_path": src_dir / "config" / "settings.json",
        "default_inputs_path": project_root / "data" / "inputs.sample.json",
        "default_output_dir": project_root / "data",
    }

def load_settings(path: Path, logger: logging.Logger) -> Dict[str, Any]:
    settings = load_json_file(path, logger=logger)
    if not isinstance(settings, dict):
        logger.warning("Settings file invalid or missing; using defaults.")
        settings = {}
    return settings

def build_http_settings(settings: Dict[str, Any]) -> HttpSettings:
    http_conf = settings.get("http", {}) if isinstance(settings, dict) else {}
    scraper_conf = settings.get("scraper", {}) if isinstance(settings, dict) else {}

    return HttpSettings(
        user_agent=http_conf.get(
            "user_agent", "Mozilla/5.0 (compatible; BaytJobsScraper/1.0; +https://bitbash.dev)"
        ),
        timeout=int(http_conf.get("timeout", 15)),
        max_retries=int(http_conf.get("max_retries", 3)),
        backoff_factor=float(http_conf.get("backoff_factor", 0.5)),
        proxies=http_conf.get("proxies") or None,
        delay_between_requests_seconds=float(scraper_conf.get("delay_between_requests_seconds", 1.0)),
    )

def parse_args(default_inputs: Path, default_output_dir: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape job listings from Bayt.com and export structured data."
    )
    parser.add_argument(
        "--inputs",
        type=Path,
        default=default_inputs,
        help="Path to input JSON file with search URLs configuration.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional explicit output file path. If not provided, uses settings or default.",
    )
    parser.add_argument(
        "--format",
        dest="fmt",
        type=str,
        default=None,
        help="Export format: json, jsonl, csv, excel, xml, html.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Override maxItems for each search in the inputs file.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    )
    return parser.parse_args()

def read_inputs(path: Path, logger: logging.Logger) -> Dict[str, Any]:
    config = load_json_file(path, logger=logger)
    if not isinstance(config, dict):
        logger.error(
            "Input configuration %s is missing or invalid; "
            "expected a JSON object with 'searches' key.",
            path,
        )
        return {"searches": [], "output": {}}
    if "searches" not in config or not isinstance(config["searches"], list):
        logger.warning("Inputs file missing 'searches' list; using empty list.")
        config["searches"] = []
    if "output" not in config or not isinstance(config["output"], dict):
        config["output"] = {}
    return config

def main() -> None:
    paths = resolve_paths()
    setup_logging()
    logger = get_logger("BaytJobsScraper")

    args = parse_args(paths["default_inputs_path"], paths["default_output_dir"])

    # Adjust log level from CLI
    try:
        logging.getLogger().setLevel(args.log_level.upper())
    except ValueError:
        logger.warning("Invalid log level '%s'; using INFO.", args.log_level)
        logging.getLogger().setLevel(logging.INFO)

    logger.info("Starting Bayt Jobs Scraper")

    settings = load_settings(paths["settings_path"], logger)
    http_settings = build_http_settings(settings)
    scraper = BaytJobScraper(http_settings=http_settings, logger=logger)

    inputs_conf = read_inputs(args.inputs, logger)
    searches: List[Dict[str, Any]] = inputs_conf.get("searches", [])
    if not searches:
        logger.error("No searches defined in inputs. Nothing to do.")
        return

    default_max_items = int(
        args.max_items
        if args.max_items is not None
        else settings.get("scraper", {}).get("default_max_items", 200)
    )

    jobs = scraper.scrape_searches(searches, max_items_fallback=default_max_items)
    if not jobs:
        logger.warning("No jobs were scraped from the given searches.")
    else:
        logger.info("Total jobs scraped: %s", len(jobs))

    # Determine output format and path
    export_conf: Dict[str, Any] = settings.get("export", {}) if isinstance(settings, dict) else {}
    input_output_conf: Dict[str, Any] = inputs_conf.get("output", {})
    fmt: str = (
        args.fmt
        or input_output_conf.get("format")
        or export_conf.get("default_format", "json")
    ).lower()

    if args.output is not None:
        output_path: Path = args.output
    else:
        output_dir = Path(
            input_output_conf.get("directory")
            or export_conf.get("default_output_dir")
            or paths["default_output_dir"]
        )
        filename = input_output_conf.get("filename") or export_conf.get(
            "default_output_filename", "output_sample.json"
        )
        output_path = output_dir / filename

    try:
        export_jobs(jobs, output_path=output_path, fmt=fmt, logger=logger)
    except Exception as exc:
        logger.error("Failed to export jobs to %s (%s): %s", output_path, fmt, exc)
        return

    logger.info("Bayt Jobs Scraper completed successfully. Output: %s", output_path)

if __name__ == "__main__":
    main()