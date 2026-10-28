# Episode 82 Regeneration Notes

## Background

Episode 82 《什么指标不赚钱》(Squeeze Momentum挤完就追) had a double-branding bug where the presenter pen name 「躺平的老黄」 appeared twice (overlapping) in the bottom-right corner of the YouTube cover/title card.

**Root cause**: The Soft Slate `00_title_card.png` already includes the branding, but `label_image` was called unconditionally in `_apply_presenter_cover`, adding it again.

## Fix Summary

PR #5 adds detection to skip labeling when branding already exists:

- `_has_bottom_right_branding()` detects existing visual signatures via HSV analysis
- `label_image()` copies pre-branded images verbatim instead of double-labeling
- Unit tests verify both blank charts (still labeled) and pre-branded images (skipped)

## Regenerating Episode 82

After the fix is merged:

```bash
# 1. Locate the approved script for ep82 (usually in data/output/ep82-*/script.json)
SCRIPT_PATH="/path/to/ep82-xxx/script.json"

# 2. Render with the fix applied
vf render --ep 82 --approved-script "$SCRIPT_PATH" --force --force-reason "Regenerate after double-brand fix"

# 3. QA the new render
vf qa --ep 82

# 4. Publish (dry-run first to verify)
vf publish --ep 82 --to youtube --dry-run
vf publish --ep 82 --to youtube --execute  # when ready
```

## Expected Outcome

The new render's cover/title card will show:
- Single presenter branding in bottom-right corner
- Clean accent bar + pen name (no overlap)
- Identical to the clean reference image provided by the user

## Related Files

- Fix: `apps/worker/src/services/presenter.py`
- Tests: `apps/worker/tests/test_presenter.py`
- PR: https://github.com/huangyuan3h/video-factory/pull/5
