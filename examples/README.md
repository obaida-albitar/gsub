# Subtitle examples

The `editing_tools_test` files tell a short story about catching the last train.
They deliberately include readability problems and formatting cases for the new
editing tools. The SRT file has **18 cues**; the ASS file shares those cues and
adds **7 ASS-specific cases**. Both are valid subtitle files and need no video
to test text editing or quality checks.

| File | Purpose |
| --- | --- |
| [editing_tools_test.srt](editing_tools_test.srt) | Quality checks, HTML formatting, split/merge/rebalance, and replacement |
| [editing_tools_test.ass](editing_tools_test.ass) | The same dialogue with ASS formatting, speakers, signs, drawings, and timed effects |
| [batch_undo_partner.srt](batch_undo_partner.srt) | A clean second SRT file for multi-file undo/redo |
| [batch_undo_partner.ass](batch_undo_partner.ass) | A clean second ASS file for timing, style, and resolution undo/redo |

Open a file with **Ctrl+O**, or run `python3 -m gsub.main examples/editing_tools_test.srt`
from the project directory. Use **Save As** for edited copies. Undo or reopen the
original between the exercises below so cue numbers keep matching this guide.

## Quality checker

Open either main sample and press **Ctrl+Shift+Q**. Set these limits before
comparing results: **20 characters/s**, **42 characters/line**, **2 lines**,
**1000–7000 ms duration**, **80 ms minimum gap**, and **overlap checks enabled**.

Expect **10 quality issues**, with these cue numbers in either format:

| Cue | Expected issue |
| --- | --- |
| 2 | Duration is only 600 ms |
| 3 | Reading speed exceeds 20 characters/s |
| 4 | A line exceeds 42 characters |
| 5 | Three lines exceed the two-line limit |
| 6 | Duration is 8 seconds |
| 8 | Overlaps cue 7 by 500 ms |
| 9 | Only a 50 ms gap after cue 8 |
| 10 | Formatting with no visible text |
| 11 | Start and end are equal: invalid duration |
| 15 | Another long line to rebalance |

Select an issue to jump to its cue. With a video loaded, the player also seeks
to the cue's start. Raise the reading-speed limit or turn off overlap checks
and confirm that the corresponding issues disappear. Each batch partner should
produce **zero issues** with the limits above.

## Split, merge, and rebalance

1. **Split cue 12:** place the text cursor just after `Meet me`, then press
   **Ctrl+Shift+K**. Expect `Meet me` and `by the ticket office.` as two italic
   cues. Their durations remain positive and meet at one shared boundary.
   Without a video, their combined range stays **38–43 seconds**; with the
   playhead inside the cue, that position supplies the split time.
2. **Merge cues 13 and 14:** Ctrl-select both and press **Ctrl+M**. Expect one
   cue from **43.300 to 49.000**, with `Keep the ticket.` above `It is our way
   home.`. Only the first sentence remains bold, including in ASS.
3. **Rebalance cue 15:** select it and press **Ctrl+Shift+B**. Expect two lines
   of similar length, with the same words and timing. Repeat with cue 4.
4. After each operation, try **Ctrl+Z**, then **Ctrl+Shift+Z**. Undo should
   restore the original text, formatting, cue count, and timing; redo should
   restore the edit.

## Find and replace

- Open the main sample and press **Ctrl+H**. Search for `ticket`. Expect
  **7 matches**, or **6** with **Whole words** enabled. `tickets` should be
  excluded by Whole words.
- For a smaller exercise, select **cue 16 before opening the dialog**, then
  enable **Selection only**. Expect **4 matches**, **3** with Whole words,
  **2** with Match case only, and **1** with both options enabled.
- Replace `ticket` with `pass` and inspect the before/after previews. Cue 17
  deliberately divides the word across inline formatting; its text should
  change while its formatting tags remain present.
- Replace All should be one undo step. Undo restores every occurrence and its
  original casing; redo restores the replacements.
- Search for `STRASSE` without Match case: cue 18's `Straße` should match.
  The same cue also exercises accented, Arabic, and Chinese text.
- In ASS, try replacing `ticket` with `boarding\Npass`: `\N` inserts a line
  break. Undo before continuing with other exercises.

## ASS-specific behavior

| Cue(s) | What to check |
| --- | --- |
| 19–20 | A sign and dialogue appear simultaneously on different styles/layers. The quality checker should accept this intentional overlap. |
| 21 | Drawing-only event: no empty-text or reading-speed warning. Split/rebalance should explain that drawing effects need manual editing. |
| 22 | Karaoke tags: split/rebalance should reject the operation without changing the cue. |
| 23 | Moving text: split should explain that the timed effect needs manual editing. |
| 24–25 | Adjacent events with different styles/layers: merge should explain the formatting conflict and leave both cues intact. |

## Multi-file batch undo/redo

1. In **Batch Operations**, add the main sample and its partner **of the same
   format**. Keep both files checked.
2. Set a time shift of **-1000 ms** and apply it. The first cue in each file
   now starts at zero; this deliberately tests clamping.
3. Press **Ctrl+Z** once. Both documents should return to their original
   state, including the first starts: **200 ms** in the main sample and
   **100 ms** in the partner. The modified badges should clear.
4. Press **Ctrl+Shift+Z** once. Both shifts and modified badges return.
5. Undo again. With the ASS pair, also enable resolution **1920×1080** and
   font size **48** for the **Default** style, then apply. One undo should
   restore timing, **1280×720**, and Default size **42** in both files.
6. Save copies with **Save All As**. Undo after saving should mark the
   in-memory documents modified; redo back to the saved state clears the
   badges. Disk files change only when you save.

Removing a batch file clears batch history. Adding files keeps it. Editor
undo/redo remains separate from batch undo/redo.

The automated real-file checks live in
[tests/test_editing_examples.py](../tests/test_editing_examples.py).

## Continuous proofreading and playhead timing

The same `editing_tools_test.srt` and `.ass` files cover the newer workflows;
no additional subtitle fixture is needed.

1. Press **Ctrl+Shift+Q**. The issue list stays beside the text editor. Filter
   to **Line length**, select cue 4 or 15, and use **Preview Rebalance Fix**.
   Confirm the before/after text, apply it, then undo and redo. The issues
   should update without closing the panel.
2. Filter to **Short duration**, select cue 2 and choose **Ignore Issue**.
   Close and reopen the panel: the warning should remain ignored. Change the
   cue's text to make the warning eligible again, or use **Reset Ignored**.
3. Load a video and select a cue inside its duration. Seek within that cue;
   use **Ctrl+Alt+S** and **Ctrl+Alt+E** to set its start and end. Each change
   is one undo step. An end before the start should be rejected.
4. Open the player's cue menu. Set lead-in/out to **500 ms** and playback speed
   to **0.75**. **Ctrl+Alt+P** plays once and pauses; **Ctrl+Alt+L** loops the
   cue and toggles the loop off. Selecting another cue should stop the loop.
5. Click the current-time readout or press **Ctrl+G**. Enter `00:00:01.250`,
   `0:01.250`, or `1.250` and press Enter or **Go**. The three forms request
   the same position. Try invalid text and a time beyond the video: an inline
   error should appear without moving the playhead. Repeat while paused and
   while playing to confirm that navigation preserves the playback state.
6. Pause, zoom into the timeline with **Ctrl+scroll**, and seek repeatedly.
   The marker should follow the latest request and settle on the decoded
   frame. Use **,** and **.** for frame steps. A 24 fps video has frames about
   41.7 ms apart, so a typed timestamp may display a nearby frame timestamp.

For save protection, work on scratch copies: make a pending text edit, then
try opening another file, creating a document, removing a modified batch file,
and closing the app. Cancel should retain the edit; Save should finish before
the requested action proceeds. Cancelling Save As for an untitled document
must also cancel that action. Automated recovery tests simulate interruption,
restore SRT/ASS and unchecked batch documents, and verify that failed writes
preserve the original files.
