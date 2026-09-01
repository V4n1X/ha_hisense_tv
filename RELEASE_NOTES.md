# Release Notes — v1.3.6

Reverts the optimistic state updates from v1.3.5 so sensors always show live values reported by the TV.

## 🔄 Changed

- **No more optimistic pre-writes:** volume up/down, mute and source selection no longer locally assume the resulting state. Sensors exclusively reflect what the TV actually reports through its push feedback (`volumechange`, `sourceswitch`) — "live values only".

  Rationale: the earlier behaviour was confirmed in practice — the TV pushes `sourceswitch` immediately (source sensor felt instant even without the optimistic write), while the `volumechange` push arrives with a 1–2 s delay on some firmwares. Rather than guessing, the integration now documents that delay as intentional.

- **Documented:** the README troubleshooting table now states that volume/source sensors update 1–2 s after a command because values are live TV pushes, not local guesses.

- The direct volume slider (`media_player.volume_set`) keeps its long-standing echo behaviour, which is deduplicated against the TV's push feedback.

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisensetv/compare/v1.3.5...v1.3.6) for the complete list.
