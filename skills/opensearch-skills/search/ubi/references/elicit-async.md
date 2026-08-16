# Async elicitation: the questionnaire

The branch of Elicit for a room missing its people: when the user confirms
that the owners of the answers (product, analytics, sales, whoever holds
the goals) are not present, the elicitation goes to them on paper. One
shared document, answered independently, disagreement surfaced rather than
averaged: a single Delphi-style round.

## Generate

Write **`ubi-questionnaire.md`** at the application repo's root. The fixed
name is the re-entry trigger; never vary it. The page carries whichever
cells the room could not settle: the whole Goals → Signals → Metrics
ladder when the owners were absent from the start, or just the cells a
live Elicit parked as unsure, each under the role the user says owns it.
It is built from the same material as live Elicit (the ladder, prompted
across both axes, grounded in the Audit's facts), and it obeys the
session's language rule harder than the room does: its readers are further
from the code than anyone in the terminal.

- **A header for strangers.** What this page is, in three plain sentences;
  who asked for it; how to answer: inline, under each question, in their
  own words.
- **One section per stakeholder role the user names**, each addressed to its
  reader. Goals questions come first, in the product's own words, prompted
  across both axes so the answers are not all task-success by default: what
  the people searching want, and what the business wants from search. Signal
  questions ground each goal in the app's audited actions, offered as a plain
  menu ("when someone finds what they need, what do they do on the page?").
  Metric questions ask how the reader would judge, in numbers, that the
  goal is met, and what number they would call success. A closing
  question asks which single number they would watch to know search is
  delivering what the business wants from it, and what must not get worse
  while it improves; without it the page comes back unable to settle
  Elicit's close.
- **The business question goes on the page whether or not a business role
  was named.** Absent owners are what this file is for, and the owners most
  often absent are the ones who hold this answer, so it is asked in the
  business's own terms rather than as another question about the page: what
  the team is trying to move, how search is meant to help move it, and where
  that would show up in numbers the business already watches. A reader who
  has no such outcome says so, and that answer settles the cell as firmly as
  a named one; a page that never asked leaves it unsettled, which is a
  different thing and Elicit's Check tells them apart.
- **Batches of two or three questions**, each numbered and emoji-marked:
  a page is scanned at its reader's own pace, so the batching live Elicit
  forgoes is right at home on paper. The recommended answers the
  terminal carries stay off the paper: respondents answer independently,
  and a pre-filled recommendation would anchor exactly the disagreement
  the round exists to surface.

## Circulate

The fork comes first, put to the user plainly: continue now with what is
settled (the floor plus the confirmed goals capture correctly from day
one) while the questionnaire carries the unsure cells to their owners, or
hold the elicitation until the answers return.

Hand the file to the user to circulate however the team works, then follow
the fork they chose: continuing, the session goes on from the settled rows;
holding, it ends here. Either way, the close is a handover a stranger
could pick up, someone who was never in this session: what is built and
verified, which cells wait on whom, and the resume phrase (start any
later session and ask to continue the UBI setup; the questionnaire will
be found).

## Ingest: on re-entry

- **Unanswered or partly answered:** name the empty sections and ask the
  user whether to keep waiting or continue live with whoever is present.
- **Answered:** read every section, then **reconcile**:
  - Where two stakeholders' goals pull in different directions (one wants
    exploration up, another wants the shortest path to a purchase), name
    the tension to the room in plain language. Where the pull is a user
    want against a business want, ask first whether one **bounds** the
    other rather than beats it: a headline on one axis with the other as
    its guardrail keeps both measured, and two roles answering from two
    axes is what the round was built to collect, not evidence that one of
    them is wrong. Only where the two are genuinely incompatible does the
    user decide which goal governs. Conflicts are decided by people,
    never averaged by you.
  - What survives becomes the raw material for the live Goals → Signals →
    Metrics table, built and confirmed in-session as ever: the
    questionnaire feeds Elicit; it never replaces the confirmed table.
  - When the app was instrumented on the minimal path meanwhile, the
    answers extend rather than reopen: new rows join the mapping through
    Map's approval as ever, and only the new rows' emitters are
    implemented and verified; settled instrumentation stays settled.

## Delete

When the confirmed table carries everything the answers gave, delete the
file and say so. The Critical Rules' carve-out is exactly this window: the
questionnaire exists while it circulates, and not a session longer.

**Check:** a deferral session ends with the file in the repo and the user
told the resume phrase. An ingestion ends with every conflict named and
decided, the confirmed table absorbing the answers, and the file gone.
