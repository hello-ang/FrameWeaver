
lines = {}
for line in open("C:/Users/ru'bin/tasks_recovered.txt", encoding="utf-8"):
    if line.startswith(tuple(str(i) + ":" for i in range(10))):
        parts = line.split(":", 1)
        if len(parts) == 2:
            num = int(parts[0])
            content = parts[1].strip("\r\n")
            if content.startswith(" "): content = content[1:]
            lines[num] = content

with open("recovered.py", "w", encoding="utf-8") as f:
    for i in range(1, max(lines.keys()) + 1):
        f.write(lines.get(i, f"# MISSING LINE {i}") + "\n")
print("Max line:", max(lines.keys()))

