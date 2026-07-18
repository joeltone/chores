# How the Chore Bot Works

*A plain-language guide — no coding required.*

A private Discord bot that decides who does what around the house, reminds people when it's due, and nags an admin when it isn't done. This page explains it without any of the technical stuff — see [README.md](README.md) if you're looking for setup and deployment details instead.

## The short version

- Chores rotate automatically between everyone in the house — nobody has to remember whose turn it is.
- You get a Discord thread with your chores and a button to mark them done.
- Miss a deadline, and the admin gets pinged the next morning.
- Your chores can also show up in Google Calendar, on their own private link.

---

## 1. How chores get assigned

Everyone in the house is on a list, in a fixed order. Each chore moves down that list one person at a time — whoever had it last, the next person in line gets it next.

```
Cal (just did it) → Morgy (next) → Patch → Rock Eater → back to Cal
```

Some people can be permanently skipped for specific chores — say, nobody wants Cal anywhere near *mop the office*. That's set up once and the bot remembers it from then on:

```
Cal (excluded from this chore) → Morgy (next) → Patch → Rock Eater → back to Cal
```

For a chore Cal is excluded from, the bot just skips straight to Morgy.

## 2. Your daily rhythm

Two things happen automatically, every day, without anyone lifting a finger:

| Time | What happens |
|---|---|
| **8:00 AM** | New chores get handed out. Anything due for reassignment is posted to whoever's next, grouped into a thread with their name on it. |
| **9:00 AM** | Overdue chores are flagged. Anything still unchecked from a previous due date gets marked overdue, and the admin is pinged in the channel. |

If the bot ever restarts — an update, a reboot, whatever — nothing is lost. Every "mark done" button picks up right where it left off.

## 3. Marking a chore done

Open your thread in the chores channel and click **✅ Mark Completed** under the chore. The button greys out and records the time. That's it — nothing to type, nothing to confirm.

Want a private list instead of scrolling the thread? Type `/chore mine` anywhere in the server and the bot will reply to you privately with everything you still owe and when it's due.

## 4. Seeing what's coming

Two commands cover most curiosity:

- `/chore mine` — just your pending chores, sent privately.
- `/chore upcoming` — everyone's chores due in the next 7 days, posted to the channel.

## 5. Syncing to your calendar

Run `/user calendar` and the bot replies — privately — with a personal link. Paste that link into Google Calendar under **Settings → Add calendar → From URL**, and your chores show up as all-day events on their due dates. It keeps itself up to date; you never have to re-paste it.

> **Keep that link to yourself.** It's tied to you specifically — anyone with the link can see your chore schedule. If you ever think it's gotten out, ask the admin to run `/user rotate-token` and your old link stops working.

Prefer a one-off file instead of a live subscription? `/chore export` downloads your schedule as a calendar file you can import anywhere.

## 6. Going away for a while

Traveling, sick, whatever — you don't have to keep up with chores while you're out, and you don't come back to a pile-up either.

- The admin pauses you with `/user pause`. Anything currently open on your plate is reassigned to the next person right away — nothing sits waiting on you.
- When you're back, `/user reinstate` puts you at the *end* of the rotation. No backlog, no catch-up chores — you just wait your turn like everyone else.

## 7. If something's overdue

Nothing happens silently. A chore that passes its due date without being marked done gets flagged **⚠️ overdue**, and the admin is pinged about it the next morning at 9. The admin can also check `/admin escalations` any time for the full list of what's currently overdue and who has it.

## 8. Every command, in plain terms

Everything is typed straight into Discord as a slash command. Commands marked **[Admin]** are restricted to the house admin — everyone else can run the rest freely.

### People

| Command | What it does |
|---|---|
| `/user add` | Adds someone to the rotation, at the back of the line. |
| `/user list` | Shows everyone in the rotation and their turn order. |
| `/user calendar` | Sends you your private calendar subscription link. |
| `/user pause` **[Admin]** | Pauses someone and hands their open chores to the next person. |
| `/user reinstate` **[Admin]** | Brings a paused person back, at the end of the line. |
| `/user remove` **[Admin]** | Removes someone from the rotation for good. |
| `/user rotate-token` **[Admin]** | Invalidates someone's calendar link and issues a new one. |

### Chores

| Command | What it does |
|---|---|
| `/chore add` | Adds a new chore and how often it repeats. |
| `/chore remove` | Retires a chore — it stops being assigned. |
| `/chore rename` | Renames a chore. |
| `/chore list` | Lists every active chore and who last did it. |
| `/chore matrix` | Shows who's eligible for what, and any exclusions. |
| `/chore mine` | Your own pending chores, sent privately. |
| `/chore upcoming` | What's due across the house in the next 7 days. |
| `/chore export` | Downloads a calendar file of someone's chore schedule. |
| `/chore exclude` | Permanently skips someone for one specific chore. |
| `/chore include` | Undoes an exclusion. |
| `/chore reassign` **[Admin]** | Manually hands an open chore to the next person, right now. |
| `/chore seed` **[Admin]** | Distributes every chore evenly — used to set up the rotation the first time. |

### Admin

| Command | What it does |
|---|---|
| `/admin escalations` **[Admin]** | Lists everything currently overdue. |
| `/admin run-assignments` **[Admin]** | Runs the 8 AM assignment job manually, without waiting for morning. |

## 9. The boring but reassuring part

This runs on a private, self-hosted Discord bot — it isn't a public service and nobody outside the house can see your chores. The only thing exposed to the outside world at all is your personal calendar link, and that's protected by a long, unguessable code that's yours alone; it can be revoked and replaced any time with `/user rotate-token`. Everything else — who's assigned what, who marked what done — stays inside the Discord server.

---

*Maintained by the house admin. For anything this page doesn't answer, just ask in the chores channel.*
