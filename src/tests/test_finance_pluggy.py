"""finance_pluggy.py with a fake HTTP opener and a fake Keychain -- no test
ever reaches api.pluggy.ai, and every id/secret/balance here is made up."""

import io
import json
import subprocess
import urllib.error
import urllib.parse

import pytest

import config
import finance_pluggy
from finance import BankSnapshot, FinanceSnapshot
from finance_pluggy import (
    PluggyClient,
    PluggyCredentials,
    PluggyError,
    bank_snapshot,
    fetch_live_balances,
    load_credentials,
    merge_live_balances,
    parse_items,
    with_live_balances,
)

CREDS = PluggyCredentials("id-falso", "segredo-falso", {"Inter BR": "item-a", "Itaú": "item-b"})


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePluggy:
    """Answers like the documented API; records every request it sees."""

    def __init__(self, *, accounts=None, investments=None, fail=None):
        self.accounts = accounts or {}
        self.investments = investments or {}
        self.fail = fail or {}
        self.calls = []

    def __call__(self, request, timeout):
        parsed = urllib.parse.urlsplit(request.full_url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        self.calls.append((request.get_method(), parsed.path, query, request.headers, request.data))
        key = (parsed.path, query.get("itemId"))
        if key in self.fail:
            raise self.fail[key]
        if parsed.path == "/auth":
            return _Response(json.dumps({"apiKey": "chave-falsa"}).encode())
        source = self.accounts if parsed.path == "/accounts" else self.investments
        results = source.get(query.get("itemId"), [])
        return _Response(json.dumps({"page": 1, "total": len(results), "totalPages": 1, "results": results}).encode())


def _client(fake):
    return PluggyClient(base_url="https://pluggy.invalid", timeout=1, opener=fake)


def _spreadsheet():
    return FinanceSnapshot(
        banks=[
            BankSnapshot("Inter BR", 100.0, 10.0, 110.0, "BRL"),
            BankSnapshot("Inter US", 20.0, 2.0, 120.0, "USD"),
            BankSnapshot("Itaú", 50.0, 0.0, 50.0, "BRL"),
            BankSnapshot("Mercado Pago", 30.0, 0.0, 30.0, "BRL"),
        ],
        gross_value=500.0,
        total_expenses=-100.0,
        projected_value=400.0,
        luxuries=-90.0,
        final_money=310.0,
    )


def test_parse_items_accepts_known_brl_banks_only():
    assert parse_items(" Inter BR=a , Itaú=b,") == {"Inter BR": "a", "Itaú": "b"}
    with pytest.raises(PluggyError, match="desconhecido"):
        parse_items("Nubank=x")
    with pytest.raises(PluggyError, match="planilha"):
        parse_items("Inter US=x")  # USD account: stays in the spreadsheet
    with pytest.raises(PluggyError, match="mal formado"):
        parse_items("Inter BR")


def test_load_credentials_reads_keychain_service_and_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(config, "PLUGGY_KEYCHAIN_SERVICE", "servico-teste")
    seen = []

    def fake_security(cmd, **kwargs):
        seen.append(cmd)
        account = cmd[cmd.index("-a") + 1]
        found = {"client_id": "id-do-keychain", "itens": "Itaú=item-b"}.get(account)
        return subprocess.CompletedProcess(cmd, 0 if found else 44, stdout=(found or "") + "\n", stderr="")

    creds = load_credentials(run=fake_security, env={"NOAH_PLUGGY_CLIENT_SECRET": "segredo-do-env"})

    assert (creds.client_id, creds.client_secret, creds.items) == ("id-do-keychain", "segredo-do-env", {"Itaú": "item-b"})
    assert all(cmd[:4] == ["security", "find-generic-password", "-s", "servico-teste"] for cmd in seen)
    assert "segredo" not in repr(creds) and "item-b" not in repr(creds)


def test_load_credentials_names_what_is_missing_without_values():
    def no_keychain(cmd, **kwargs):
        raise FileNotFoundError("security")

    with pytest.raises(PluggyError) as exc:
        load_credentials(run=no_keychain, env={"NOAH_PLUGGY_CLIENT_ID": "id-falso"})
    assert "client_secret" in str(exc.value) and "itens" in str(exc.value)
    assert "id-falso" not in str(exc.value)


def test_client_only_allows_read_endpoints():
    client = _client(FakePluggy())
    for method, path in [("POST", "/payments"), ("POST", "/pix"), ("PATCH", "/items"), ("DELETE", "/items"), ("GET", "/auth")]:
        with pytest.raises(ValueError):
            client._request(method, path)


def test_fetch_live_balances_sends_documented_requests():
    fake = FakePluggy(accounts={"item-a": [{"type": "BANK", "balance": 10.0, "currencyCode": "BRL"}]})

    fetch_live_balances(CREDS, _client(fake))

    method, path, _query, _headers, body = fake.calls[0]
    assert (method, path, json.loads(body)) == ("POST", "/auth", {"clientId": "id-falso", "clientSecret": "segredo-falso"})
    reads = fake.calls[1:]
    assert {(m, p) for m, p, *_ in reads} == {("GET", "/accounts"), ("GET", "/investments")}
    assert all(h.get("X-api-key") == "chave-falsa" for *_, h, _b in reads)
    assert all(q["itemId"] in {"item-a", "item-b"} for _m, _p, q, *_ in reads)
    assert all(q.get("type") == "BANK" for _m, p, q, *_ in reads if p == "/accounts")


def test_bank_snapshot_sums_brl_cash_and_open_investments_only():
    accounts = [
        {"type": "BANK", "balance": 100.0, "currencyCode": "BRL"},
        {"type": "CREDIT", "balance": 999.0, "currencyCode": "BRL"},  # card debt, not net worth
        {"type": "BANK", "balance": 50.0, "currencyCode": "USD"},  # not BRL: skipped, never summed as reais
    ]
    investments = [
        {"balance": 220.0, "amountOriginal": 200.0, "currencyCode": "BRL", "status": "ACTIVE"},
        {"balance": 80.0, "currencyCode": "BRL"},  # no amountOriginal: principal = balance
        {"balance": 500.0, "amountOriginal": 500.0, "currencyCode": "BRL", "status": "TOTAL_WITHDRAWAL"},
    ]

    snap = bank_snapshot("Itaú", accounts, investments)

    assert snap.total_brl == 400.0
    assert snap.invested == 380.0 and snap.yield_ == 20.0 and snap.currency == "BRL"


def test_merge_live_balances_keeps_unmapped_banks_and_recomputes_totals():
    spreadsheet = _spreadsheet()
    live = {"Inter BR": BankSnapshot("Inter BR", 200.0, 0.0, 200.0, "BRL")}

    merged = merge_live_balances(spreadsheet, live)

    assert [b.bank for b in merged.banks] == ["Inter BR", "Inter US", "Itaú", "Mercado Pago"]
    assert merged.final_money == 400.0  # 200 live + 120 + 50 + 30 from the spreadsheet
    assert merged.luxuries == 0.0  # Grana Final - Valor Previsto
    assert merged.gross_value == 500.0 and merged.total_expenses == -100.0
    assert spreadsheet.final_money == 310.0  # the original snapshot is not mutated


def test_with_live_balances_reports_source_and_partial_failures():
    fake = FakePluggy(
        accounts={"item-a": [{"type": "BANK", "balance": 200.0, "currencyCode": "BRL"}]},
        fail={("/accounts", "item-b"): urllib.error.HTTPError("u", 500, "erro", {}, None)},
    )

    merged, note = with_live_balances(_spreadsheet(), credentials=CREDS, client=_client(fake))

    assert merged.final_money == 400.0  # Itaú failed -> its spreadsheet 50 is kept
    assert "Inter BR" in note and "Meu Pluggy" in note
    assert "Itaú: a Pluggy respondeu HTTP 500" in note
    assert "item-" not in note and "segredo" not in note and "chave" not in note


def test_with_live_balances_treats_empty_item_as_expired_consent_not_zero():
    merged, note = with_live_balances(_spreadsheet(), credentials=CREDS, client=_client(FakePluggy()))

    assert merged.final_money == 310.0  # spreadsheet unchanged, not zeroed
    assert "consentimento" in note and "só a planilha" in note


def test_with_live_balances_falls_back_when_auth_fails():
    fake = FakePluggy(fail={("/auth", None): urllib.error.HTTPError("u", 401, "segredo-falso", {}, io.BytesIO(b"segredo-falso"))})

    merged, note = with_live_balances(_spreadsheet(), credentials=CREDS, client=_client(fake))

    assert merged.final_money == 310.0
    assert "HTTP 401" in note and "segredo" not in note


def test_with_live_balances_without_spreadsheet_says_total_is_partial():
    fake = FakePluggy(accounts={"item-a": [{"type": "BANK", "balance": 200.0, "currencyCode": "BRL"}]})

    merged, note = with_live_balances(None, credentials=CREDS, client=_client(fake))

    assert merged.final_money == 200.0 and merged.luxuries is None
    assert "sem a planilha" in note


def test_evaluate_investments_default_source_never_touches_pluggy(monkeypatch, tmp_path):
    from assistant import tools

    monkeypatch.setattr(config, "FINANCE_SOURCE", "planilha")
    monkeypatch.setattr(config, "PATRIMONIO_PATH", tmp_path / "nao-existe.xlsx")
    monkeypatch.setattr(finance_pluggy, "with_live_balances", lambda *a, **k: pytest.fail("Pluggy chamado"))

    assert "NOAH_PATRIMONIO_PATH" in tools.evaluate_investments()


def test_evaluate_investments_pluggy_source_merges_and_labels(monkeypatch):
    from assistant import tools

    monkeypatch.setattr(config, "FINANCE_SOURCE", "pluggy")
    monkeypatch.setattr(tools, "_publish_finance_chart", lambda snapshot: None)
    monkeypatch.setattr("finance.load_snapshot", lambda: _spreadsheet())
    live = {"Inter BR": BankSnapshot("Inter BR", 200.0, 0.0, 200.0, "BRL")}
    monkeypatch.setattr(
        finance_pluggy,
        "with_live_balances",
        lambda snapshot: (merge_live_balances(snapshot, live), "Saldos de Inter BR lidos agora no Meu Pluggy."),
    )

    reply = tools.evaluate_investments()

    assert "400,00" in reply and reply.endswith("Meu Pluggy.")


def test_evaluate_investments_pluggy_source_without_anything_explains_both(monkeypatch, tmp_path):
    from assistant import tools

    monkeypatch.setattr(config, "FINANCE_SOURCE", "pluggy")
    monkeypatch.setattr(config, "PATRIMONIO_PATH", tmp_path / "nao-existe.xlsx")
    monkeypatch.setattr(finance_pluggy, "with_live_balances", lambda snapshot: (None, "Saldos ao vivo indisponíveis (x)."))

    reply = tools.evaluate_investments()

    assert "NOAH_PATRIMONIO_PATH" in reply and "indisponíveis" in reply
