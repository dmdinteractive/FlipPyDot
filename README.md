# FlipDot Console

Controller for the 3×3 AlfaZeta XY5 flip-dot wall (84×42 dots, 18 controllers)
at Children's Museum of Denver. Runs on the Mac mini as a launchd service;
staff use it from any browser on the network.

```
./install.sh        # first time: venv, dependencies, boot service
./update.sh         # pull the latest code for the current branch and restart
./start.sh          # run in the foreground (for testing)
```

Settings live in `~/.flipdot/` (never in the repo), so updates can't wipe them.

## The tabs

| Tab | For |
|---|---|
| **Playlist** | What the wall plays, top to bottom, looping. Overlays (timed cut-ins) are tucked under it. |
| **Create** | Make text, animations, images and dashboards with a live preview. Send to the wall or add to the playlist. |
| **Texts** | Visitors text a phone number and their message appears on the wall. |
| **Setup** | USB adapters & speed, data sources/tokens, live effects, saved shows, fonts. |

## Text animation

Text is built in three steps:

- **Arrive**: just appear, split-flap, decode, typewriter, drop & bounce, rise, dissolve, swarm together, wipe, slide in.
- **While up**: hold still, wave, sparkle, jitter, bounce around, marquee lights, blink, or loop as a ticker.
- **Leave**: stay, dissolve, explode, fall away, split-flap out, backspace, wipe off. The leave is timed to finish exactly at the end of the step.

Any text can sit on a **moving background** (plasma, tunnel, warp stars, metaballs …), either cut out of it, filled with it, or inverted over it. **Recipes** set everything at once.

All effects are computed per letter and are deterministic, so the browser preview matches the wall frame for frame.

## Speed: why the wall can't fall behind

The wall is limited by two things. The discs can only flip so fast (*Max panel fps*, default 20). And at 57600 baud one USB-RS485 adapter carries about 5.7 KB/s, which is 10 full frames per second for 18 controllers.

V8 sent every controller on every frame and let `write()` queue in the OS buffer. When content ran faster than the wire, the wall drifted further and further behind. V9 (`backend/display.py`):

1. **Holds one frame, never a queue.** A new frame replaces any frame not yet sent, so stale frames are dropped rather than queued.
2. **Sends only controllers that changed.** A one-line scroll is about 3 of 18 controllers, roughly 6× less data.
3. **Paces itself to the wire.** It waits until the bytes have physically left the adapter before taking the next frame.
4. **Re-sends everything every 30 s**, so a controller that was power-cycled heals itself.
5. **Plays content by the clock.** If a frame can't be shown in time it is skipped, so a 3-second scroll still takes 3 seconds.

**Write mode.** *Immediate* uses command 0x83 (each controller flips as it arrives, same as V8). *Synced* uses 0x84 to load every changed controller, then one 0x82 to flip them all at once with no tearing. Synced hasn't been tried on this wall yet. If the panel stays blank in Synced mode, switch back.

### Adding USB adapters (up to 4)

Full-screen animation is wire-bound. Splitting the RS485 bus across more adapters multiplies the frame rate:

| Adapters | Controllers each | Full-screen fps |
|---|---|---|
| 1 | 18 | ~10 |
| 2 | 9 | ~20 |
| 3 | 6 | ~30 (then the discs are the limit) |

1. Split the RS485 daisy chain into separate runs, for example one per column of panels, and give each run its own USB-RS485 adapter. Every controller stays on 57600 baud, and the addresses can stay as they are.
2. In **Setup → Hardware**, press **+ Add adapter**, pick each adapter's port, then click controllers in the map (or use **One per column**) to match the wiring.
3. **Save & reconnect.** The live readout shows panel fps and how many controllers change per frame.

The address wizard lights controllers on all adapters at once, so keep addresses unique across adapters.

## Visitor texts (Twilio)

1. Create a Twilio account and buy a phone number with SMS.
2. Under **Texts → Twilio connection**, enter the number, Account SID and Auth Token. Leave *How messages arrive* on **Mac checks Twilio**. Nothing on the museum network needs opening, because the Mac only makes outbound HTTPS requests.
3. Flip the switch on. Use **Try it** to see how a message looks without a phone.
4. To change the look, design a text in **Create** and press **Use for visitor texts**. Size is chosen automatically per message (wrapping, smaller fonts, then scrolling for long ones).

Messages appear exactly as sent. They are not filtered. The only changes are what the dot fonts physically need: accents are folded, emoji are dropped, `{ }` become `( )` so a message can't trigger tokens, and text is cut at *Max length*. **Skip current** moves on from the message on the wall. Phone numbers are shown and logged only as their last four digits.

**Auto-reply** is off by default. Sending texts from a US 10-digit number requires A2P 10DLC carrier registration; receiving does not need a reply.

*Webhook mode* (Twilio calls the Mac) is faster but needs the Mac reachable from the internet. Requests are checked against Twilio's signature. Set the number's messaging webhook to `https://<public address>/api/sms/twilio` and enter the same URL in *Public URL*.

## Files

```
app.py                 Flask server and API
backend/display.py     serial transport: mailbox, diffing, pacing, multi-adapter
backend/player.py      the one thread that drives the display, clock-sampled
backend/clip.py        "what's on screen at time t" adapter over the renderer
backend/renderer.py    spec → frames (text, layout, animation, image)
backend/textfx.py      letter-by-letter intros/idles/outros, text over visuals
backend/visuals.py     generative visuals (plasma, tunnel, boids, maze …)
backend/sms.py         Twilio inbox → messages on the wall
frontend/              plain HTML/JS, no build step
```
