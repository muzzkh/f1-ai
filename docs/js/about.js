// About page: tool list and run instructions.

import { $, esc, context, shell, load } from "./lib.js";

const ctx = await context();
shell("about.html", ctx);
const repo = ctx.season.repo;
$("repo").href = repo;
const A = await load("about.json");
$("tools").innerHTML = (A?.tools ?? []).map((t) => `<article><h3 class="t-num">${esc(t.name)}</h3><p>${esc(t.about)}</p></article>`).join("");
$("run").textContent = [
  `git clone ${repo}.git`,
  `cd ${repo.split("/").pop()}`,
  "python -m venv .venv",
  ".venv/Scripts/python -m pip install -e .                  # macOS / Linux: .venv/bin/python",
  ".venv/Scripts/python -m streamlit run dashboard/app.py    # the dashboard",
  ".venv/Scripts/python -m f1ai.mcp_server                   # the MCP server (stdio)",
  ".venv/Scripts/python dashboard/build_site.py              # rebuild this site's data",
].join("\n");
