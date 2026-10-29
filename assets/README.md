# Native animation source

The Codex character artwork is by OpenAI. `codex-v6.rgba.z` is a lossless zlib
packing of the RGBA pixels from the Codex v6 atlas in the locally installed
OpenAI.Codex 26.1021.3705.0 desktop app. Its source and pixel hashes are recorded
in `codex-v6.json`. Attribution does not place that artwork under this app's
MIT code license.

Cells are 192×208 in an 8×11 grid. The first nine rows contain complete
animation poses; the last two contain sixteen gaze directions. Runtime
recoloring preserves the original pixels, alpha, alignments and limb poses.
Pip does not load or change the Codex app at runtime.

References checked for the implementation:

- [Official Pets documentation](https://learn.chatgpt.com/docs/pets)
- [Public atlas player and timing definitions](https://github.com/thanh-abaii/codex-pet/blob/main/src/renderer.ts)
- [Public v2 atlas contract](https://github.com/MakerCore/hatch-pet/blob/main/references/codex-pet-contract.md)

The installed desktop renderer confirms the same state timing, a 6× slower
6.6-second idle loop, and default width 7.04rem (112.64 logical pixels at the
standard 16px root font). Pip applies monitor DPI once to that display size.
Whole frames keep the authored arm and leg movement intact. No source code
from the desktop renderer was copied.
