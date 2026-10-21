"""Read-only per-bank balances from Meu Pluggy (the free consumer tier of
Pluggy's Open Finance API), layered on top of the user's own spreadsheet
(finance.py). Off by default: only runs when NOAH_FINANCE_SOURCE=pluggy.

What it does, and nothing more:
- POST /auth with the user's own client_id/client_secret -> a short-lived
  apiKey (kept in memory for this one call, never written anywhere);
- GET /accounts and GET /investments for each Item the user linked in
  Meu Pluggy, summing BRL bank accounts + investment balances per bank.
Those three are the only endpoints _request() accepts -- no payment, Pix,
transfer or Item-editing call can be made through this module, even by
mistake. Nothing is cached on disk: every question is a fresh read.

The bank password never passes through Noah -- consent is given inside
the bank's own app/site when the user links it in Meu Pluggy. Noah only
needs three values, read from the macOS Keychain (service
config.PLUGGY_KEYCHAIN_SERVICE, accounts "client_id", "client_secret",
"itens") or, as a fallback, from NOAH_PLUGGY_CLIENT_ID /
NOAH_PLUGGY_CLIENT_SECRET / NOAH_PLUGGY_ITEMS. "itens" maps a bank from
finance.BANKS to its Item: "Inter BR=<itemId>,Itaú=<itemId>". None of
these ever belong in the repository, tests, logs or replies.

Banks left out of the map (e.g. Inter US, a USD account no Meu Pluggy
connector was confirmed for) keep their spreadsheet figures, and so does
every bank whose live read fails -- a partial answer is labelled as such,
never presented as the whole picture.

API shape checked against docs.pluggy.ai (auth-create, accounts-list,
investments-list) on 2026-10-20; no live call was made while writing
this module.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Callable

import config
from finance import BANKS, BankSnapshot, FinanceSnapshot, _USD_BANKS

# The whole allow-list of calls this module can make -- see module docstring.
_ALLOWED_CALLS = {("POST", "/auth"), ("GET", "/accounts"), ("GET", "/investments")}
_MAX_PAGES = 20
# Investment positions that no longer hold money (Pluggy marks fully
# withdrawn ones this way) must not be summed into the balance.
_CLOSED_INVESTMENT_STATUSES = {"TOTAL_WITHDRAWAL"}


class PluggyError(Exception):
    """A short, safe message: never contains a secret, an Item id or a
    response body -- it can be shown to the user and spoken aloud."""


@dataclass
class PluggyCredentials:
    client_id: str
    client_secret: str = field(repr=False)
    items: dict[str, str] = field(repr=False)  # bank -> Item id


def parse_items(raw: str) -> dict[str, str]:
    """ "Inter BR=abc, Itaú=def" -> {"Inter BR": "abc", "Itaú": "def"}.
    Only BRL banks from finance.BANKS are accepted, so a typo can't
    silently create a fifth bank and Inter US can't be summed as BRL."""
    items: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        bank, sep, item_id = (piece.strip() for piece in part.partition("="))
        if not sep or not bank or not item_id:
            raise PluggyError("O mapa de bancos do Pluggy está mal formado (use Banco=item,Banco=item).")
        if bank not in BANKS:
            raise PluggyError(f"Banco desconhecido no mapa do Pluggy: {bank}.")
        if bank in _USD_BANKS:
            raise PluggyError(f"{bank} fica na planilha (conta em dólar).")
        items[bank] = item_id
    if not items:
        raise PluggyError("Nenhum banco ligado ao Pluggy no mapa de itens.")
    return items


def _keychain_value(account: str, *, run: Callable = subprocess.run) -> str | None:
    try:
        result = run(
            ["security", "find-generic-password", "-s", config.PLUGGY_KEYCHAIN_SERVICE, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None  # not macOS, or Keychain unavailable -- try the env fallback
    value = (result.stdout or "").strip()
    return value if result.returncode == 0 and value else None


def load_credentials(*, run: Callable = subprocess.run, env=None) -> PluggyCredentials:
    env = os.environ if env is None else env
    values = {}
    for account, env_name in (
        ("client_id", "NOAH_PLUGGY_CLIENT_ID"),
        ("client_secret", "NOAH_PLUGGY_CLIENT_SECRET"),
        ("itens", "NOAH_PLUGGY_ITEMS"),
    ):
        values[account] = _keychain_value(account, run=run) or (env.get(env_name) or "").strip() or None
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise PluggyError(f"Faltam credenciais do Pluggy no Keychain: {', '.join(missing)}.")
    return PluggyCredentials(values["client_id"], values["client_secret"], parse_items(values["itens"]))


class PluggyClient:
    def __init__(self, *, base_url: str | None = None, timeout: float | None = None, opener: Callable | None = None):
        self.base_url = (base_url or config.PLUGGY_API_URL).rstrip("/")
        self.timeout = config.PLUGGY_TIMEOUT_SECONDS if timeout is None else timeout
        self._open = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, *, query=None, body=None, api_key: str | None = None) -> dict:
        if (method, path) not in _ALLOWED_CALLS:
            raise ValueError(f"chamada fora da lista de leitura: {method} {path}")
        url = self.base_url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            headers["X-API-KEY"] = api_key
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PluggyError(f"a Pluggy respondeu HTTP {exc.code} em {path}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise PluggyError("sem conexão com a Pluggy") from None
        except ValueError:
            raise PluggyError(f"resposta inválida da Pluggy em {path}") from None
        if not isinstance(payload, dict):
            raise PluggyError(f"resposta inválida da Pluggy em {path}")
        return payload

    def authenticate(self, credentials: PluggyCredentials) -> str:
        payload = self._request(
            "POST", "/auth", body={"clientId": credentials.client_id, "clientSecret": credentials.client_secret}
        )
        api_key = payload.get("apiKey")
        if not isinstance(api_key, str) or not api_key:
            raise PluggyError("a Pluggy não devolveu a chave de acesso")
        return api_key

    def _results(self, path: str, query: dict, api_key: str) -> list[dict]:
        results: list[dict] = []
        page = 1
        while page <= _MAX_PAGES:
            payload = self._request("GET", path, query={**query, "page": page}, api_key=api_key)
            batch = payload.get("results")
            if not isinstance(batch, list):
                raise PluggyError(f"resposta inválida da Pluggy em {path}")
            results.extend(r for r in batch if isinstance(r, dict))
            total_pages = payload.get("totalPages")
            if not isinstance(total_pages, int) or page >= total_pages:
                break
            page += 1
        return results

    def accounts(self, item_id: str, api_key: str) -> list[dict]:
        return self._results("/accounts", {"itemId": item_id, "type": "BANK"}, api_key)

    def investments(self, item_id: str, api_key: str) -> list[dict]:
        return self._results("/investments", {"itemId": item_id}, api_key)


def _brl(record: dict, key: str) -> float | None:
    if (record.get("currencyCode") or "BRL") != "BRL":
        return None
    value = record.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def bank_snapshot(bank: str, accounts: list[dict], investments: list[dict]) -> BankSnapshot:
    """Cash in BRL bank accounts (credit cards are a debt, not net worth,
    so type CREDIT is excluded even if the filter were ignored upstream)
    plus open BRL investment positions. Like the spreadsheet's "Dinheiro
    Total", total_brl is the figure that adds up across banks."""
    cash = sum(v for a in accounts if a.get("type", "BANK") == "BANK" and (v := _brl(a, "balance")) is not None)
    invested = 0.0
    current = 0.0
    for position in investments:
        if position.get("status") in _CLOSED_INVESTMENT_STATUSES:
            continue
        balance = _brl(position, "balance")
        if balance is None:
            continue
        original = _brl(position, "amountOriginal")
        current += balance
        invested += original if original is not None else balance
    return BankSnapshot(bank=bank, invested=cash + invested, yield_=current - invested, total_brl=cash + current, currency="BRL")


def fetch_live_balances(
    credentials: PluggyCredentials, client: PluggyClient | None = None
) -> tuple[dict[str, BankSnapshot], list[str]]:
    """Banks read live, plus a note per bank that couldn't be (those keep
    the spreadsheet). Raises PluggyError only when nothing can be read at
    all (bad credentials, no network)."""
    client = client or PluggyClient()
    api_key = client.authenticate(credentials)
    live: dict[str, BankSnapshot] = {}
    notes: list[str] = []
    for bank in BANKS:
        item_id = credentials.items.get(bank)
        if not item_id:
            continue
        try:
            accounts = client.accounts(item_id, api_key)
            investments = client.investments(item_id, api_key)
        except PluggyError as exc:
            notes.append(f"{bank}: {exc}")
            continue
        if not accounts and not investments:
            # Expired Open Finance consent comes back as empty lists, not an
            # error -- a zero here would be a wrong answer, not a real one.
            notes.append(f"{bank}: sem dados (o consentimento pode ter expirado no Meu Pluggy)")
            continue
        live[bank] = bank_snapshot(bank, accounts, investments)
    return live, notes


def merge_live_balances(snapshot: FinanceSnapshot | None, live: dict[str, BankSnapshot]) -> FinanceSnapshot:
    """A new snapshot (the spreadsheet's one is left untouched) where every
    bank read live replaces its spreadsheet row, and the two totals that
    depend on bank balances are recomputed the same way the spreadsheet's
    Contas tab defines them: Grana Final = sum of every bank's total,
    Luxos = Grana Final - Valor Previsto."""
    base = snapshot or FinanceSnapshot()
    by_bank = {b.bank: b for b in base.banks}
    by_bank.update(live)
    banks = [by_bank[name] for name in BANKS if name in by_bank]
    final_money = sum(b.total_brl for b in banks) if banks else None
    luxuries = (
        final_money - base.projected_value
        if final_money is not None and isinstance(base.projected_value, (int, float))
        else None
    )
    return replace(base, banks=banks, final_money=final_money, luxuries=luxuries)


def with_live_balances(
    snapshot: FinanceSnapshot | None, *, credentials: PluggyCredentials | None = None, client: PluggyClient | None = None
) -> tuple[FinanceSnapshot | None, str]:
    """The entry point evaluate_investments uses: the merged snapshot and
    one short sentence saying where the numbers came from. On any failure
    the spreadsheet snapshot comes back unchanged (or None if there's no
    spreadsheet either) with the reason."""
    try:
        live, notes = fetch_live_balances(credentials or load_credentials(), client)
    except PluggyError as exc:
        return snapshot, f"Saldos ao vivo indisponíveis ({exc}); usei só a planilha."
    if not live:
        return snapshot, "Saldos ao vivo indisponíveis (" + "; ".join(notes) + "); usei só a planilha."
    merged = merge_live_balances(snapshot, live)
    source = f"Saldos de {', '.join(live)} lidos agora no Meu Pluggy"
    rest = [b.bank for b in merged.banks if b.bank not in live]
    if snapshot is None:
        source += "; sem a planilha, o total só soma esses bancos"
    elif rest:
        source += f"; {', '.join(rest)} vêm da planilha"
    if notes:
        source += " (" + "; ".join(notes) + ")"
    return merged, source + "."
