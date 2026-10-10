const { spawnSync } = require("child_process");
const args = ["start.py", ...process.argv.slice(2)];
for (const py of ["python", "py", "python3"]) {
  const r = spawnSync(py, args, { stdio: "inherit", cwd: __dirname });
  if (!r.error) process.exit(r.status ?? 0);
}
console.error("Python 3.10+ not found: https://python.org");
process.exit(1);
