# Writable work area

Everything the server writes goes here. Keep curated inputs in
`../sample_files/` unchanged. This directory is ignored by Git apart from
this README and the `.gitkeep` placeholders.

- `models/uploads/`: user-provided models.
- `models/derived/`: copies and edited versions of models. Edits without an
  explicit `output_path` land here.
- `runs/`: simulation outputs and run records (the default
  `output_directory`).
- `reports/`: generated diagrams, viewers, and other reports.
