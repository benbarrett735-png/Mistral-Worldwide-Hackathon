# Critical assessment: what’s wanted, what works, what’s left to win

## What the hackathon wants (from README, FINAL_FLOW, judging guide)

| Want | Source |
|------|--------|
| **Two Mistral AI models** (Helpstral + Flystral) with clear roles | README, PROJECT_PLAN |
| **User app**: “Walk me home”, set destination, real walking route, order drone, see drone follow, distress button | FINAL_FLOW, README |
| **Mission control**: live map, drone status, camera feed, Helpstral overlay (SAFE/DISTRESS), Flystral commands | FINAL_FLOW, README |
| **Drone behaviour**: hub → user (straight), escort along **user’s walking route**, then straight home | You (Louvre hub, escort = walking route) |
| **Distress**: user taps “I need help” → countdown → no dismiss → emergency (e.g. “police called”) | mistral_drone_hackathon_guide.txt |
| **Demo narrative**: Summon drone → mission control shows deploy → drone arrives → walk with phone, drone follows → false alarm dismiss → real attack → distress → countdown → “police called” (second phone) → drone returns | mistral_drone_hackathon_guide.txt |
| **Judging**: practice demo 10+ times, backup video, show **both code and working demo**, social impact, speak clearly | JUDGING TIPS |

---

## What we’ve actually done that works

### Working end-to-end

1. **User app (Google Maps–style)**  
   - Full-screen map, search (Nominatim), origin/destination, **real OSRM walking route**, “Request drone escort”, ETA, “Start walking”.  
   - WebSocket on load; **live drone position** on map when mission is running.  
   - **Distress**: “I need help” → 15s countdown → sends `emergency` on WebSocket; dismiss cancels.

2. **Mission control layout**  
   - **Top left**: map (same as user).  
   - **Top right**: ArduPilot SITL Live (mode, armed, phase, WP, lat/lon/alt, **scrolling ArduPilot/connector log**).  
   - **Bottom half**: mission info, phases, telemetry, SITL, waypoint files, camera placeholder, Vision AI, event log.

3. **Real ArduPilot SITL (no mock)**  
   - Hub **hard-set at Louvre** (48.8606, 2.3376).  
   - `start_sitl.sh` starts ArduCopter + MAVProxy; server can auto-start SITL.  
   - **mavlink_connector**: connects to SITL, uploads waypoints, arms, takeoff, AUTO mission, **streams real MAVLink telemetry** over WebSocket.  
   - **Route**: approach/return straight; **escort = user’s walking route** (OSRM → waypoints).  
   - Mission Control and User App both show **same live drone** from one mission.

4. **App and missions linked**  
   - One backend, one WebSocket; `mission_update` and `mission_started` from `_current_mission`.  
   - User orders → Mission Control gets same mission and same live stream.

5. **Backend APIs**  
   - `/api/route` (OSRM walking route), `/api/order` (plan mission, ETA), `/api/mission/start` (start SITL mission).  
   - `/api/helpstral` and `/api/flystral` exist and call **Mistral vision API** (image → SAFE/DISTRESS and image → command).

6. **Vision AI UI in Mission Control**  
   - Helpstral and Flystral cards; event log; emergency banner when `emergency` received.

---

## What still doesn’t work or is missing (to actually win)

### Critical (demo / narrative)

1. **No real camera feed for the AI models**  
   - Mission Control has a “Drone camera” panel and `runHelpstral()` every 5s taking frames from `<video id="droneFeed">`.  
   - **`droneFeed` is never given a stream** (no `getUserMedia` or simulated feed).  
   - So **Helpstral never runs on real (or any) imagery** in the live demo; status stays “Awaiting feed”.  
   - **Fix**: Either (a) use **user’s phone camera** (getUserMedia) as “what the drone sees” for demo, or (b) feed a **static/sample image or short loop** into `droneFeed` so Helpstral (and optionally Flystral) actually run and show SAFE/DISTRESS and commands.

2. **Flystral not in the live loop**  
   - Flystral is only called if something POSTs `/api/flystral` with an image.  
   - Mission Control doesn’t call it; the old **mock** that sent flystral events was removed with the mock sim.  
   - So **no FOLLOW/AVOID/CLIMB etc. appear during the demo**.  
   - **Fix**: In Mission Control, when escort phase is active and we have a frame (same as Helpstral), call `/api/flystral` periodically and broadcast the result (or have server do it and broadcast), and show it in the Flystral card + log.

3. **“Police called” / second phone is theatre**  
   - Guide says: “Real attack → click distress → phone rings → 15s countdown → No dismissal → police called (show second phone)”.  
   - We only have: countdown → WebSocket `emergency` → Mission Control shows “EMERGENCY — USER DISTRESS DETECTED”.  
   - **Fix**: Add a clear **demo moment**: e.g. “Alert sent” / “Calling emergency services…” on user app after countdown, and in the script **show a second phone** (or browser tab) “receiving” the alert so judges see the story.

4. **README and docs out of date**  
   - README still describes **mock simulator** and Gare du Nord; we use **real ArduPilot SITL** and **Louvre** hub.  
   - **Fix**: Update README (and any other docs) to say ArduPilot SITL, Louvre, and current flow (plan → start → live telemetry, Helpstral/Flystral on camera feed).

### Important (credibility / judging)

5. **Mistral usage: prompt vs fine-tuned**  
   - README says “fine-tuned Pixtral 12B” for Helpstral and Flystral.  
   - Code uses **Mistral API** with a **vision-capable model + prompt** (no custom fine-tune in repo).  
   - **Fix**: Either (a) **actually fine-tune** and use that model ID in config, or (b) **change wording** to “Mistral vision API (Pixtral) with task-specific prompts” so judges aren’t misled.

6. **Demo reliability**  
   - SITL + MAVProxy + pymavlink depend on env (ArduCopter binary, Python, ports).  
   - **Fix**: **Practice full demo 10+ times**; have a **backup video** (record: user app → order → start → Mission Control with map + ArduPilot panel + distress + “police” moment) if live SITL fails.

7. **Pitch and narrative**  
   - Guide: 30s intro, then show app, mission control, drone deploy, tracking, false alarm, real distress, countdown, “police”, drone return, “€3 per use”.  
   - **Fix**: Write a **one-page script** (with timestamps) and rehearse so both code and narrative are clear and social impact is stated.

### Nice to have

8. **Flystral actually changing the mission**  
   - Spec says: user deviates → Flystral replans; obstacle → avoid.  
   - Today Flystral is vision → command only; **no wiring** to inject waypoints or change ArduPilot mission in real time.  
   - For hackathon, **showing Flystral commands in the UI** (from live camera) is likely enough; full replan can stay “future work”.

9. **Login / auth**  
   - FINAL_FLOW says “dummy for 48h demo”.  
   - Safe to leave as-is for the competition.

---

## Prioritised to-do list to win

| Priority | Task | Why |
|----------|------|-----|
| **P0** | **Give Mission Control a real image source for “drone camera”** (e.g. getUserMedia from laptop, or a demo image/loop) and ensure **Helpstral runs** and shows SAFE/DISTRESS in the UI. | Judges need to see the **first** Mistral model doing something visible. |
| **P0** | **Call Flystral from Mission Control** (same frame as Helpstral, or every N s during escort) and **display** command in Flystral card + event log. | Judges need to see the **second** Mistral model in the loop. |
| **P0** | **Distress → “Alert sent / Calling emergency services”** on user app + **scripted “second phone”** moment in the pitch. | Delivers the promised narrative and impact. |
| **P1** | Update **README** (and any pitch deck) to match reality: ArduPilot SITL, Louvre, no mock, current flow. | Credibility and “show code”. |
| **P1** | **Record a 4–5 minute backup video** of the full flow (user app + Mission Control + distress + “police”) and **rehearse live demo 10+ times**. | Judging tips: backup if tech fails, practice. |
| **P1** | Clarify **Mistral**: either use a fine-tuned model and say so, or describe as “Mistral vision API + prompts” in README and pitch. | Honesty and technical clarity. |
| **P2** | One-page **demo script** with timings and key phrases (social impact, €3, “two AI models”). | Clear, confident pitch. |

---

## One-line summary

**What works:** Real ArduPilot SITL, Louvre hub, user walking route → waypoints, linked user + mission control UIs with live drone and ArduPilot panel, distress countdown + WebSocket emergency, and working Helpstral/Flystral APIs.  

**What’s missing to win:** A real image feed so Helpstral (and Flystral) run visibly in the demo, Flystral wired into the live UI loop, a clear “emergency / police” moment in the narrative, and up-to-date docs + backup video + rehearsed pitch.
