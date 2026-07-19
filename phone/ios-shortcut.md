# iOS Shortcut — voice capture

Build a Shortcut that dictates a task and posts it to your board via the n8n capture workflow (`n8n/2-add-agent-task.json`).

## Actions (in order)

1. **Dictate Text**
   - Language: your language
   - Stop Listening: **After Pause**

2. **If** — Dictated Text **has any value**
   *(a guard so an empty/cancelled dictation posts nothing. Put the next two actions inside this If.)*

3. **Get Contents of URL**
   - **URL:** your n8n capture **Production** URL, e.g. `https://YOUR_N8N_HOST/webhook/add-agent-task-XXXXXX`
   - **Method:** POST
   - **Headers:** `Content-Type` = `application/json`
   - **Request Body:** **JSON** → **one** field:
     - Key = `task`
     - Value = the **Dictated Text** variable

4. **Show Notification** (optional) → "Agent task added ✅"

5. **End If**

## Wire up triggers

- **Back Tap:** Settings → Accessibility → Touch → Back Tap → Double/Triple Tap → this Shortcut.
- **Siri:** just say "Hey Siri, <the Shortcut's name>".
- **Home/Lock screen:** Shortcut ⋯ → Add to Home Screen, or a Lock Screen widget.

## On iPad (or any second device)

The Shortcut **syncs automatically** via iCloud (Settings → Apps → Shortcuts → iCloud Sync, same Apple ID) — no rebuild. But iPad has **no Back Tap and no Action Button**, so use one of these triggers instead:

- **Siri** — "Hey Siri, <Shortcut name>". Fully hands-free, the best default.
- **AssistiveTouch** (the Back Tap replacement): Settings → Accessibility → Touch → AssistiveTouch → On, then **Custom Actions** → assign **Long Press** (or Double-Tap) to run this Shortcut. A floating button is then one gesture from dictation.
- **Home/Lock screen or Today widget** — add an icon or a Shortcuts widget.
- **Control Center** (iPadOS 18+) — add a Shortcuts control.
- **Spotlight** — swipe down, type the Shortcut name, return.

> Permissions are **per-device**: the first run on a new device re-prompts for **microphone/speech** and **"Allow to contact your n8n host"**. Tap Allow on both, or it silently fails.

## Gotchas (learned the hard way)

- **The URL must be the `/webhook/` Production URL**, not the `/webhook-test/` one (test URLs fire once).
- **Body = one field named `task`.** ClickUp's picker labels rows "Key" and "Value"; make sure the field's *name* is `task` and the *value* is the Dictated Text variable — don't create fields literally named "Key"/"Value". (The n8n workflow tolerates that mistake via `$json.body.task || $json.body.Value`, but do it right.)
- **First run permission:** iOS asks to allow the Shortcut to contact your n8n host — tap **Allow**, or every run silently fails.
- Speak a beat longer before pausing; "After Pause" can cut off early.
