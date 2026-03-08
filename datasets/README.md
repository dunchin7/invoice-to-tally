# Benchmark Dataset Layout

This folder stores the benchmark corpus used by `evaluation/run_eval.py`.

## Structure

- `source_docs/`: Source invoices (PDF/image) used for extraction (directory scaffold only; keep large/binary docs out of git unless required).
- `ground_truth/`: Gold JSON labels. File stem must match prediction file stem.

Example pair:

- `source_docs/<doc_id>.pdf|png|jpg`
- `ground_truth/<doc_id>.json`
- prediction file: `outputs/<doc_id>.json`

## Adding a new vendor/template

1. Add the raw invoice document into `source_docs/` with a unique stem (for example `acme_jan_2026.pdf`).
2. Create the matching labeled JSON in `ground_truth/` (for example `acme_jan_2026.json`) using the project invoice schema.
3. Generate model output JSON with the same stem in your predictions directory.
4. Run evaluation:

   ```bash
   python evaluation/run_eval.py \
     --ground-truth-dir datasets/ground_truth \
     --predictions-dir outputs \
     --report-dir evaluation/reports
   ```
5. Check threshold gate status in the JSON summary before release.

## Labeling tips

- Keep numeric fields (`subtotal`, `tax`, `total`, line-item quantities/prices) as numbers.
- Keep dates and textual fields exactly as they appear in invoice normalization output.
- Include every required schema key so metrics are comparable across vendors.
