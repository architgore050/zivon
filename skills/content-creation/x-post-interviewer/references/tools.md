# Free editing tools with MCP servers (researched Oct 2026, verify before installing)

Everything below is third-party community software. Read the repo, check the install command, and run it in a
folder you control. Star counts were small for several of these, so treat them as young projects.

## Recommended default for local models: FFmpeg-based MCP
Why: FFmpeg is free, runs offline, and handles trim/crop/concat/subtitles/audio/export. Small local models do
better with FEW tools, so prefer the smallest server that does the job.
- ffmpeg-mcp-lite: 8 tools (trim, merge, convert, compress, extract audio or frames, burn in subtitles).
  Install line reported in a 2026 roundup: `claude mcp add ffmpeg uvx ffmpeg-mcp-lite` (needs `uv`).
- free-video-edit-mcp (breverdbidder): FFmpeg/ffprobe wrapper, 16 tools, MIT, stdio or local HTTP. Needs Python
  3.10+, FFmpeg 7.x on PATH, and an env var FREE_VIDEO_EDIT_ROOT pointing at your projects folder.
- Kinocut (formerly mcp-video): reported ~87 tools including subtitles, audio, effects and preflight checks.
  Powerful but a big tool list can overwhelm a small local model. Use it only if your model handles many tools.

## If you want a real timeline editor
- DaVinci Resolve (free edition) + a Free-compatible MCP bridge. One repo (hiteshK03/davinci-resolve-mcp) claims
  to work on the free edition with ~44 tools and local Whisper transcription; another (emircbngl/davinci-resolve-
  mcp-free) uses FCPXML export, Lua snippets and macOS UI automation. The most-starred community server
  (samuelgursky/davinci-resolve-mcp) is reported to need Resolve Studio (paid) for external scripting.
  Setup is heavier and Resolve must be open on the same machine.

## Photos and screenshots
- GIMP 3.0+ MCP server (gimp-mcp-server, MIT): layers, selections, filters, export. Needs GIMP 3 with Python and
  GTK4/GObject system libraries, so setup is the most painful part of this whole list.
- Cheaper path for screenshots: crop, annotate with one box/arrow, export PNG. Do this by hand in any free editor
  or via FFmpeg crop/scale; an MCP is overkill for static screenshots.

## MCP host for a local model
Any MCP-capable client works, but the LOCAL MODEL must support tool calling. Check that before blaming the server.
Test with one command ("trim clip.mp4 from 2s to 9s and export") before running the full edit brief.

## Suggested first setup (cheapest path)
1. Install FFmpeg. 2. Add ffmpeg-mcp-lite. 3. Run one trim test. 4. Run the edit brief step by step.
5. Only if you need a timeline UI, add DaVinci Resolve free.
