# Issue drafts, not yet filed

Drafts for `awtoau/awto-renode-rs`, written during the 2026-08-02 session and
kept here because they were living in gitignored `tmp/` and would not have
survived a clean.

They are **drafts**, not a tracker. Once filed, the file goes and the issue is
the record — a draft that outlives its issue becomes a second source of truth
for work in progress, which is why `docs/issues-draft.md` was deleted earlier.

| file | what |
|---|---|
| [0-close-55](0-close-55.md) | comment to close #55 with the measured result |
| [0-status-52](0-status-52.md) | #52 acceptance audit: interleaving oracle built, runtime measurement blocked |
| [0-status-58](0-status-58.md) | implementation/status record for #58 with current full-tree counts |
| [1-dsl-families](1-dsl-families.md) | **LANDED** — four register-DSL families |
| [2-tag-overmatch](2-tag-overmatch.md) | **LANDED** — 171 anonymous fields emitted as tags |
| [3-loop-builder](3-loop-builder.md) | **LANDED, premise wrong** — see the note at the top |
| [4-unread-corpus-facts](4-unread-corpus-facts.md) | partly landed; the ingest half was reverted |
| [5-subblocks-latent](5-subblocks-latent.md) | open |
| [6-adc-behaviour-gap](6-adc-behaviour-gap.md) | **DIAGNOSED, not fixable** — adc1's 1,192 are a behaviour gap this oracle cannot reach |
| [6-selector-by-name](6-selector-by-name.md) | **LANDED** — `scripts/register_owners.py` selects by content; see the `sel-` drafts for what it uncovered |
| [sel-1-dictionary-form-drops-the-reset-value](sel-1-dictionary-form-drops-the-reset-value.md) | open — a register located through a dictionary always resets to 0 |
| [sel-2-unresolved-field-emits-the-identifier-UNKNOWN](sel-2-unresolved-field-emits-the-identifier-UNKNOWN.md) | open — `st.f.UNKNOWN` instead of a gap |
| [sel-3-conditional-combinator-chains-are-dropped-in-silence](sel-3-conditional-combinator-chains-are-dropped-in-silence.md) | open — `.If().Then().Else()` fields vanish |
| [p2-not-in-the-corpus](p2-not-in-the-corpus.md) | open — deferred only for want of instances |

The `sel-` drafts were all found by the same change: the register-owner
selector now picks a type's register-defining member by what its body CONTAINS,
so the peripherals that build their map in a constructor are emitted for the
first time. Three defects were waiting in code nothing had ever run. They carry
a prefix rather than the next number because several agents draft at once and
the numbers collide.

Three landed the same night they were drafted, so file those as **closed** with
their result, or not at all — filing them as open would misdescribe the tree.
