# FormAI Checkpoint

Created at: 2026-03-17 01:20:14 Europe/Istanbul

Checkpoint name: `20260317_012014_formai_multiline_split_v2_checkpoint`

Saved state:
- Multiline form fields now support `lead + body` widget segmentation
- Continuation area detection fixed so the middle line is not skipped
- Extractor and assembler now merge and split segmented fields transparently
- Updated tests for heuristic detection and segmentation behavior
- Generated `split_v2` fillable PDF and filled demo output

Included in archive:
- `src/`
- `tests/`
- `README.md`
- `pyproject.toml`
- `ornek/`
- `tmp/ornek_pipeline_fillable_split_v2.pdf`
- `tmp/ornek_pipeline_fillable_split_v2_filled_demo.pdf`
- `tmp/ornek_pipeline_fillable_split_v2_filled_demo_page1.png`

Verification summary:
- `env PYTHONPATH=src ./.venv311/bin/python -m unittest discover -s tests -v`
- Result: `Ran 10 tests ... OK`
- Generated field count: `27`

Restore note:
- Extract `project_snapshot.tar.gz` into the project root to restore this checkpoint snapshot.
- Git reference for this checkpoint will be added after commit/tag creation.
