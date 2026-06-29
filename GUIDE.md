# Chore Bot — Happy Path

## Initial Setup

### 1. Add users
```
/user add @Cal
/user add @Morgy
/user add @Patch of sentient moss
/user add @~Rock Eater~
```

### 2. Add chores (if not using seed script)
```
/chore add   name: Wash dishes   frequency_days: 1
/chore add   name: Tidy kitchen  frequency_days: 2
```

### 3. Set exclusions (if not using seed script)
```
/chore exclude @Cal   chore_name: Mop Alec's office
```

### 4. Seed initial assignments
```
/chore seed
```
Each person gets a Discord thread in the chores channel with their assigned chores. Due dates are staggered across each chore's frequency window.

---

## Daily Life

**Mark a chore done** — click ✅ Mark Completed in your thread. The button greys out and timestamps the completion.

**See your pending chores**
```
/chore mine
```

**See what's coming up**
```
/chore upcoming
```

---

## Admin Actions

**Someone's going away**
```
/user pause @Cal
```
Their open chores immediately reassign to the next person in rotation.

**They're back**
```
/user reinstate @Cal
```
They re-enter the rotation at the back of the queue. No catch-up assignments.

**Check overdue chores**
```
/admin escalations
```
The bot also pings you daily at 9am for anything overdue.

**Rename a chore**
```
/chore rename   old_name: Wash dishes**   new_name: Wash dishes
```

---

## Calendar Sync

Each person runs once to get their private URL:
```
/user calendar
```
Paste the URL into Google Calendar → **Settings → Add calendar → From URL**. It auto-refreshes and shows all pending chores as all-day events on their due dates.

If a URL is compromised:
```
/user rotate-token @Cal
```

---

## Automation

| Time | What happens |
|------|-------------|
| 8:00 AM daily | New assignments posted as per-user threads |
| 9:00 AM daily | Overdue chores escalated; admin pinged |
| On restart | All incomplete chore buttons re-registered automatically |
