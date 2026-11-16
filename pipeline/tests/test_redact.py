from alas3.redact import MASK, redact_text, restriction_reason


def test_person_cuil_masked_company_cuit_kept():
    text = "Encargado CUIL 20-12345678-3. Proveedor Pinturas SA CUIT 30-71234567-9"
    out = redact_text(text)
    assert "12345678" not in out
    assert "30-71234567-9" in out


def test_cuil_without_dashes_masked():
    assert "27123456784" not in redact_text("cuil 27123456784")


def test_dni_labeled_and_dotted():
    assert "12.345.678" not in redact_text("DNI 12.345.678")
    assert "23456789" not in redact_text("D.N.I. Nº 23456789")
    assert redact_text("titular 30.123.456 firma") == f"titular {MASK} firma"


def test_amounts_are_not_mistaken_for_dni():
    for amount in ("$ 12.345.678,00", "12.345.678,50", "$12.345.678"):
        assert redact_text(f"Total {amount}") == f"Total {amount}"


def test_cbu_masked():
    out = redact_text("CBU 0170099220000067797370 o 0170 0992 2000 0067 7973 70")
    assert "0170099220000067797370" not in out
    assert "7973" not in out


def test_restriction_reasons():
    assert restriction_reason("RECIBO DE HABERES - Ley 20744") == "payroll"
    assert restriction_reason("Formulario F.931 AFIP") == "payroll"
    assert restriction_reason("Listado de morosos al 30/09") == "debtors"
    assert restriction_reason("Rubro 1 Sueldos y cargas sociales   1.000,00") is None


def test_debt_block_hidden_rest_of_page_kept():
    from alas3.redact import page_policy

    text = "\n".join(
        [
            "SUELDO ENCARGADO  1,000,000.00",
            "E.P.E.C.  90,000.00",
            "Total de Gastos del Período: 01/2026  1,090,000.00",
            "Unidades con deudas al: 01/2026  Importe Mora Edificio: 9.876.543,21",
            "9/A 901  111.111,00  8/H 802  222.222,00",
            "VENCIMIENTO DE LAS EXPENSAS COMUNES: 12/02/2026",
        ]
    )
    pol = page_policy(text)
    assert pol.restricted is None
    assert pol.hidden_lines == {3, 4}


def test_debt_listing_pages_are_restricted():
    from alas3.redact import page_policy

    for text in (
        "Detalle de deuda por UF\nUF 1  10.000,00\nUF 2  20.000,00",
        "Estado de cuentas por unidad funcional\nsaldo",
        "UF 12 saldo deudor 123.456,00\nUF 13  1.000,00\nUF 14  2.000,00\nUF 15  3.000,00",
        "Deudores al 31/01",
    ):
        assert page_policy(text).restricted == "debtors", text


def test_scanned_empty_page_restricted():
    from alas3.redact import page_policy

    assert page_policy("", scanned=True).restricted == "no_text"
    assert page_policy("   ", scanned=False).restricted is None


def test_more_dni_forms_and_sensitive_strings():
    from alas3.redact import sensitive_strings

    assert "12345678" not in redact_text("Documento Nacional de Identidad 12345678")
    assert "345" not in redact_text("dni 12 345 678")
    found = sensitive_strings("CUIL 20-12345678-3 y CUIT 30-71234567-9, DNI 23.456.789")
    assert "20-12345678-3" in found and "23.456.789" in found
    assert not any("71234567" in s for s in found)


def test_debtors_counted_per_unit_not_per_row():
    """Review #4: four units per row; two rows without a header are 8 debtors."""
    from alas3.redact import page_policy

    rows = [
        "9/A 901  111.111,00  8/H 802  222.222,00  6/E 603  333.333,00  5/F 504  444.444,00",
        "otro texto",
    ]
    assert page_policy(rows).restricted == "debtors"


def test_debt_block_continues_on_next_page():
    from alas3.redact import page_policy

    first = page_policy(["Gastos  1,00", "texto", "otro", "Unidades en mora:", "9/A 901  111.111,00"])
    assert first.open_block and first.restricted is None
    second = page_policy(
        ["8/H 802  222.222,00", "VENCIMIENTO 12/02", "resto", "de la", "pagina"], carry_in=True
    )
    assert second.hidden_lines == {0}


def test_row_indexes_do_not_shift_on_odd_separators():
    """Review #10: str.splitlines would split on \\x0c and shift every later index."""
    from alas3.redact import page_policy

    rows = ["a\x0cb", "c", "d", "Unidades con deudas al: 01/2026", "9/A 901  111.111,00", "VENCIMIENTO"]
    assert page_policy(rows).hidden_lines == {3, 4}


def test_review_identifier_forms():
    for t in (
        "DNI N°: 12345678",
        "CUIL 20 - 12345678 - 9",
        "CUIL: 20-12345678- 9",
        "DU 12345678",
        "M.I. 12345678",
    ):
        assert "12345678" not in redact_text(t), t
    assert "12345678" not in redact_text("CUIL 21-12345678-9")  # labelled CUIL: any prefix
    assert redact_text("CUIT 30-71234567-9") == "CUIT 30-71234567-9"  # companies stay


def test_barcode_number_starting_with_a_person_cuit_is_masked():
    """The digits under an old AFIP barcode start with the issuer's CUIT (invented here)."""
    from alas3.redact import redact_text, sensitive_strings

    run = "2011111111206000123456789012345202601015"
    assert redact_text(f"CAE {run}") == "CAE [oculto]"
    assert run in sensitive_strings(f"x {run} y")
    company = "3011111111206000123456789012345202601015"
    assert redact_text(company) == company  # companies' barcodes stay


def test_utility_payment_barcode_is_not_mistaken_for_a_cuit():
    from alas3.redact import redact_text, valid_cuit

    run = "2400000000106000123456789012345202601015"  # starts with 24, but no valid CUIT check digit
    assert not valid_cuit(run[:11])
    assert redact_text(run) == run
