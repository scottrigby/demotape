# v0.7.0: tmux-backed terminal sessions (run-once, multi-dim render)

## Context

Today's terminal-session pipeline runs `vhs` once per `(session, dim)` pair, **re-executing the same commands each time**. That's safe for read-only demos (`echo`, `ls`, `kubectl get`), but actively dangerous for write-ops demos (`helm upgrade`, `kubectl apply`, `git push`) because side effects fire N times — once per dim.

Goal: keep multi-dim rendering of the same session, but execute commands exactly **once**. Implementation: one server-side **tmux** session per `session: <id>`, N **VHS clients** attaching simultaneously at different dims, an orchestrator that drives commands via `tmux send-keys` while all clients capture in real time.

Side-benefit: removes the "all occurrences of one session must use the same pane dimensions" constraint we currently validate and error on. Mixed-dim sessions become a first-class feature instead of a foot-gun.

## Architecture

For each session in the YAML:

1. **One detached tmux server-side session** at canonical width 80 cols, height = smallest row count across all client dims. `window-size manual` so client attaches don't resize it.
2. **N VHS clients in parallel**, each with a tape that does:
   ```
   Output "<session>_<W>x<H>.mp4"
   Set Width <W>, Set Height <H>, Set FontSize <auto>
   Hide
   Type "tmux attach -t <session>"   Enter
   Sleep 500ms
   Show
   Sleep <total_session_duration + buffer>ms
   ```
   Font size is computed per-dim so 80 cols fills the post-padding inner width (`font ≈ inner_w / (cols × 0.6)`).
3. **Orchestrator** (Python) waits for all clients to be attached (`tmux list-clients -t <sid>` polled until count == N), then walks the session's per-step actions in order, driving each via `tmux send-keys`:
   - `type:` → `send-keys -l <char>` per character with `time.sleep(0.050)` between (visible typing animation, identical look to current VHS Type)
   - `paste:` → `send-keys -l <chunk>` + `Enter` per chunk (instant, identical to current behavior)
   - `enter:` → `send-keys Enter`
   - `sleep_ms:` → `time.sleep(N/1000)`
   Records `(step_idx, cursor_ms, target_ms)` offsets as it goes.
4. **VHS clients finish** when their tape's trailing `Sleep` ends. Tmux session is killed.
5. **Per-step slicing** of each client MP4 reuses the existing `_slice_session_video` + scaled-offsets logic unchanged.

Browser panes and non-session terminal panes are untouched.

## Spike first (must pass before refactoring)

A standalone script `scripts/spike_tmux_vhs.py` that:
- Starts `tmux new-session -d -s spike -x 80 -y 18`
- Spawns 2 VHS subprocesses in parallel: tape A at `1920×1080` (font 40), tape B at `960×540` (font 20), both attaching to `spike`
- Polls `tmux list-clients -t spike` until 2 clients connected
- Sends 3 commands via `tmux send-keys` with simulated typing
- Waits for both VHS to finish; kills the tmux session
- Verifies both MP4s exist and `ffprobe` returns sane durations

If the spike works, proceed. If tmux+VHS attach has a surprise (window-size weirdness, attach failure, garbled rendering), reconsider before touching `recorder.py`.

## Files to modify

### `src/showtape/recorder.py`
- **Add** `_render_sessions_via_tmux(sessions, work_dir) → session_videos` — the new orchestrator. Returns the same `{(sid, dims): (mp4_path, offset_map)}` dict the current code produces, so Pass 3 needs no changes.
- **Add** helpers:
  - `_compute_session_geometry(unique_dims, cols=80)` → `(rows, {dims: font_size})`
  - `_build_attach_tape(sid, dims, font_size, total_ms, mp4_path)` → tape text
  - `_drive_actions_via_tmux(sid, actions) → used_ms` — mirrors `_emit_terminal_actions` but sends to live tmux instead of emitting tape lines
  - `_wait_for_clients(sid, n, timeout_s=10)` — polls `tmux list-clients`
- **Replace** Pass 2 in `render()` (lines 676–711): instead of the per-dim VHS loop using `_compile_session_tape_for_dim`, call `_render_sessions_via_tmux(sessions, work)`.
- **Delete** `_compile_session_tape_for_dim` (recorder.py:500) — no longer used.
- **Keep unchanged**:
  - `_collect_terminal_sessions` (recorder.py:474)
  - `_unique_session_dims` (recorder.py:491)
  - `_emit_terminal_actions` (recorder.py:377) — still used by per-step terminal panes via `compile_tape`
  - `_slice_session_video`, `_measure_video_duration_ms`
  - `record_terminal_pane` (per-step path, recorder.py:456)
  - `compile_tape`, `_tape_header`
- **Drop** the "same-dim across occurrences" validation (it currently lives wherever `_collect_terminal_sessions`'s output gets sanity-checked) since mixed dims are now supported.

### `feature/showtape/devcontainer-feature.json`
- Append `,tmux` to the `apt-packages` feature's `packages` string.

### `README.md`
- Replace the "Constraint: all occurrences of one session must use the same pane dimensions" sentence with a note that sessions support mixed dims (different layouts in different steps). Mention that commands run once — safe for write-ops.

### `ARCHITECTURE.md`
- Update the "Terminal sessions are multi-rendered, one VHS run per unique pane size" bullet under "Choices worth knowing" to describe the tmux model.

### `demos/terminal-sessions.yaml`
- Optional: add a step that performs a write-op (`mkdir /tmp/showtape-demo && touch /tmp/showtape-demo/file.log`) to visually demonstrate the run-once property.

## Verification

1. **Spike passes** — both MP4s render at correct dims, content matches, no tmux errors.
2. **Existing demo regression** — `showtape render demos/terminal-sessions.yaml` produces an MP4 visually equivalent to the current 0.6.2 output. Sessions show correct continuity, mixed dims render at correct scale, no command-rerun side effects.
3. **Write-op test** — Add a YAML step that creates a file. Run `showtape render`. Confirm via `ls /tmp/showtape-demo/` afterward that the file exists exactly once (not N times).
4. **Sanity** — `ffprobe out/terminal-sessions.mp4` shows expected duration, audio track present, video stream at 1920×1080.
5. **CI green** on a feature branch before merging to `main`.

## Out of scope for v0.7.0

- True per-dim line-wrap (different text wrap at different physical widths). Bytestream is canonical at 80 cols; all renders show the same wrap pattern at different physical scales. This is a known and acceptable trade-off for the run-once guarantee.
- Aspect-ratio extremes (e.g., 1920×540 alongside 960×1080 in the same session). Current pragmatic behavior: pick smallest row count, taller clients see empty space below the content area. Document this; revisit if a real demo hits it.
- Cross-session copybuffer (paste from session A into session B) — still on the v0.10.0+ list.

## Branch + release plan

- Branch: `feat/v0.7.0-tmux-sessions`
- Spike commit lands first, recorder refactor second, docs third.
- `scripts/bump-version.sh 0.7.0` once verification is green; CI publishes the OCI feature.
