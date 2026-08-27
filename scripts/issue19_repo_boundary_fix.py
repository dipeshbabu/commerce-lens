from pathlib import Path

path = Path("commercelens/domain/repository.py")
text = path.read_text()
text = text.replace("from commercelens.jobs.migrations import run_postgres_migrations\n", "")

old_path = (
    '    path = getattr(store, "path", None)\n'
    '    return SQLiteDomainRepository(path or os.getenv("COMMERCELENS_JOBS_DB", "commercelens_jobs.db"))\n'
)
new_path = (
    '    path = getattr(store, "path", None)\n'
    '    sqlite_path = str(path) if path is not None else os.getenv("COMMERCELENS_JOBS_DB", "commercelens_jobs.db")\n'
    '    return SQLiteDomainRepository(sqlite_path)\n'
)
if old_path in text:
    text = text.replace(old_path, new_path, 1)
elif new_path not in text:
    raise RuntimeError("Repository path anchor not found")

old_init = (
    "        self._dict_row = dict_row\n"
    "        with self._connect() as conn:\n"
    "            run_postgres_migrations(conn)\n"
)
new_init = (
    "        self._dict_row = dict_row\n"
    "        from commercelens.jobs.migrations import run_postgres_migrations\n\n"
    "        with self._connect() as conn:\n"
    "            run_postgres_migrations(conn)\n"
)
if old_init in text:
    text = text.replace(old_init, new_init, 1)
elif new_init not in text:
    raise RuntimeError("Postgres migration import anchor not found")

path.write_text(text)
