## UI brief: views (Tree, Connect, Ledger, shared header)

Data: every name, figure, quote and source URL is read from `docs/flagship/data-brief.json` (gated). Booking pills only for exact names in `ui/dossier_booking.json`.

Component map (element → existing component, or new):
- Skip link → new: `bf-skip` (44px pill, `--bg2`, 1px `--accent` border, focus ring token)
- Header bar, wordmark, six links → new: `bf-top` + `bf-nav`, built from landing/method `.wordmark` and method `nav.top a` (13.5px, `--dim`, `--ink` on hover); current page = `--ink` + 1px `--accent` rule
- Menu / Close / Change pill (760px and narrower) → explorer `button.go`
- Kicker → `.kicker`; page h1 with italic terracotta `<em>` → landing/method `h1`
- Kitchen inputs and suggestion list → explorer `input#q`, `.sugg` (adds a Kitchen/Chef type label)
- Grow / Trace → explorer `button.go`
- Summary figures (61 / 6 / 15, Ledger leaders) → landing `.stats .stat`
- Tree / List switch → explorer `.viewtoggle` with `aria-pressed`
- Star marks → explorer `.rosterlist .st` (`--stargold`), always a text ★ and part of the accessible name
- Person, role, year, quotation, source line, outlet badge → explorer `.pname`, `.role`, `.tlyr`, `.ev` (as `<blockquote>`), `.src`, `.srcbadge`
- Stop and hop line in the citation panel → explorer `.tl` timeline (`.tldot`, `.tlrail`), rail in `--dim`
- Booking pills → explorer `.bookrow a`, `.res`
- copy link / save image → explorer `.copybtn`; flag or add → explorer `.flaglink`
- Ledger bars → explorer `.pedbar`; Ledger table → method `table`, `th`, `td`
- New, no existing equivalent: ring layout (`.guide` rings, radial labels, outer ring of marks with hover/focus names), descent layout (chips reuse the explorer `treeSVG` chip), Connect `ol.line` with stations and direction chevrons, generation bar on phone, share card (1200×630), phone menu panel

Tree drawing rules:
- Branch line: `--dim`. Branch that leads to a starred kitchen: `--gold`. Selected branch: `--ink`. `--faint` only for hairlines and the guide rings.
- Heavier line: two or more distinct cited moves (distinct person and source article) join the same two kitchens.
- Rings 1 and 2: every kitchen named at 12.5px, never scaled. A second-move kitchen that leads on is named along its branch; one with a long name is named outside its own fan of marks.
- Ring 3: one mark per kitchen, attached to its real parent. A starred mark shows ★ and its name. Any mark shows its name on hover and on focus (`.lab.tip`). The open branch names its mark.
- Slots: a named kitchen takes one slot of arc; a third-move mark takes 0.45 of a slot; a first-move kitchen with no children takes the same arc length as a second-move name. When the slots need more than the circumference at 13px per slot, the radii grow together and the page scrolls.
- Motion: one line reveal and fade, under 600ms in total; none under `prefers-reduced-motion`.

Tokens: only the existing `:root` set (`--bg --bg2 --ink --dim --faint --accent --gold --stargold --ok --bad`). Literals reused from explorer: `#7d7361` (placeholder), `#7dcec8` (SFGate badge), `#e7b0a4` (Chronicle badge). No new colours.

State matrix:
- Loading → applies; not mocked. Reuse explorer `.loading`.
- Empty → applies; Connect picking state mocked; Tree with no branch open mocked (large tree file).
- No chain / unknown name / same kitchen twice → applies; not mocked. Reuse explorer `.empty`; copy from the plan: "No chain of cited moves joins these two kitchens yet."
- Error and retry → applies; not mocked. Reuse explorer `.err`.
- Partial → applies; the plan's caps ("+N more kitchens") are not mocked because no tree in the brief reaches them.
- Disabled → applies; Trace is `aria-disabled` until both ends are picked (mocked).
- Hover / focus-visible / pressed → applies; mocked: open branch (`aria-current`), a hovered third-move mark with its name (Four Kings), skip link focused, Menu open.
- One vs many → applies; kitchens with 0, 1, 2 and 8 children are all in the drawn tree.
- Long text → applies; long names wrap to two lines or are cut with an ellipsis, with the full name in `<title>`, the accessible name and the list. A quotation cut by the data ends with an ellipsis.
- Narrow and wide → applies; 390 and 1440 mocked. At 760px and narrower the Tree is the list only.
- Themes → one theme (warm dark).
- Reduced motion → applies.
- Destructive actions, live updates → N/A (read-only views).

Verification list: warm dark × 1440 and 390 × {Tree with open branch, Tree idle at 71 kitchens, Tree list, Connect pick, Connect two-move result, Ledger, header skip link, Menu open}.

Not changed: explorer, landing and method page bodies; only the header is shared with them.
