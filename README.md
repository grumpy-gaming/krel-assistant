# Stevie (krel-assistant)

Stevie is the assistant built into [KrelboyneOS](https://krelboyneos.org). Ask it about your computer in plain words, and it looks things up with real tools instead of guessing: disk space, memory, battery health, temperatures, failed services, error logs, packages and KOS Doctor's checkup. It can also fix things, install software and open apps, but it always shows you what it is about to do and waits for your yes first.

**Status:** early development (Phase 1: text only). Voice comes later.

## Try it

```sh
git clone https://github.com/grumpy-gaming/krel-assistant.git
cd krel-assistant
bin/stevie "what's using my disk space?"
bin/stevie            # chat; type exit or press Ctrl+D to leave
bin/stevie --tools    # what Stevie can do
```

Needs Python 3.11 or newer and nothing else from outside Python's standard library.

## Which AI it uses

By default Stevie uses a free model running on your own computer through [Ollama](https://ollama.com), so nothing leaves your machine. You can point it at a cloud AI instead with a key of your own.

Settings live in `~/.config/krel-assistant/config.toml`; every line is optional:

```toml
provider = "ollama"            # ollama, gemini, openrouter or openai
model = "qwen3:4b-instruct"
# base_url = "http://192.168.1.50:11434/v1"   # e.g. Ollama on another computer on your network
# api_key = "..."              # or set GEMINI_API_KEY / OPENROUTER_API_KEY / OPENAI_API_KEY instead
# timeout = 120
```

If you put a key in the file, make it private (`chmod 600 ~/.config/krel-assistant/config.toml`); Stevie refuses to use a key other users can read. One-off switches work too: `bin/stevie --provider gemini --model gemini-2.5-flash "..."`.

**Privacy:** with Ollama, everything stays on your computer. With a cloud provider, your questions and the tool results Stevie sends (for example parts of your system logs) go to that provider.

## Safety

- Tools that only look run on their own. Tools that change anything (fixes, installs, opening apps, shell commands) show exactly what they will do and need your yes.
- Anything that needs administrator rights asks you for your password through sudo. Stevie never stores or sees it.
- Without a terminal to ask in, Stevie answers no to every change.

## Tests

```sh
python3 -m unittest -v
```

The tests use a fake AI and a throwaway home folder, so they need no model and never touch your files.

## License

GNU General Public License v3.0 or later; see [LICENSE](LICENSE). The Stevie and KrelboyneOS names identify this project; forks are welcome under their own name.

Ideas borrowed with thanks from [Bliss-26 Subkernel](https://github.com/Mandelbroccoli-digital/Bliss-26_Subkernel) by Owl_6055 / Greg (MIT): swappable AI providers, and a system prompt that makes the AI check before it claims anything about the machine.
