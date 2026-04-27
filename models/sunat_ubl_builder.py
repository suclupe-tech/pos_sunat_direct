from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape
from odoo import fields


class SunatUBLBuilder:

    @staticmethod
    def _money(value):
        return Decimal(str(value or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @staticmethod
    def _line_values(line):
        qty = Decimal(str(line.qty or 0)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

        total_linea = SunatUBLBuilder._money(line.price_subtotal_incl)
        subtotal_linea = SunatUBLBuilder._money(line.price_subtotal)
        igv_linea = SunatUBLBuilder._money(total_linea - subtotal_linea)

        precio_unitario_con_igv = (
            SunatUBLBuilder._money(total_linea / qty) if qty else Decimal("0.00")
        )

        precio_unitario_sin_igv = (
            SunatUBLBuilder._money(subtotal_linea / qty) if qty else Decimal("0.00")
        )

        return {
            "qty": qty,
            "total": total_linea,
            "subtotal": subtotal_linea,
            "igv": igv_linea,
            "precio_con_igv": precio_unitario_con_igv,
            "precio_sin_igv": precio_unitario_sin_igv,
        }

    @staticmethod
    def _build_invoice_lines(order):
        lines_xml = ""

        valid_lines = order.lines.filtered(lambda l: l.qty and l.price_subtotal_incl)

        for index, line in enumerate(valid_lines, start=1):
            vals = SunatUBLBuilder._line_values(line)
            product_name = escape(line.product_id.display_name or "PRODUCTO")

            lines_xml += f"""
    <cac:InvoiceLine>
        <cbc:ID>{index}</cbc:ID>
        <cbc:InvoicedQuantity unitCode="NIU">{vals["qty"]}</cbc:InvoicedQuantity>
        <cbc:LineExtensionAmount currencyID="PEN">{vals["subtotal"]:.2f}</cbc:LineExtensionAmount>

        <cac:PricingReference>
            <cac:AlternativeConditionPrice>
                <cbc:PriceAmount currencyID="PEN">{vals["precio_con_igv"]:.2f}</cbc:PriceAmount>
                <cbc:PriceTypeCode>01</cbc:PriceTypeCode>
            </cac:AlternativeConditionPrice>
        </cac:PricingReference>

        <cac:TaxTotal>
            <cbc:TaxAmount currencyID="PEN">{vals["igv"]:.2f}</cbc:TaxAmount>
            <cac:TaxSubtotal>
                <cbc:TaxableAmount currencyID="PEN">{vals["subtotal"]:.2f}</cbc:TaxableAmount>
                <cbc:TaxAmount currencyID="PEN">{vals["igv"]:.2f}</cbc:TaxAmount>
                <cac:TaxCategory>
                    <cbc:Percent>18.00</cbc:Percent>
                    <cbc:TaxExemptionReasonCode>10</cbc:TaxExemptionReasonCode>
                    <cac:TaxScheme>
                        <cbc:ID>1000</cbc:ID>
                        <cbc:Name>IGV</cbc:Name>
                        <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
                    </cac:TaxScheme>
                </cac:TaxCategory>
            </cac:TaxSubtotal>
        </cac:TaxTotal>

        <cac:Item>
            <cbc:Description>{product_name}</cbc:Description>
        </cac:Item>

        <cac:Price>
            <cbc:PriceAmount currencyID="PEN">{vals["precio_sin_igv"]:.2f}</cbc:PriceAmount>
        </cac:Price>
    </cac:InvoiceLine>
"""

        return lines_xml

    @staticmethod
    def build_invoice_xml(order, tipo, serie, correlativo):
        cliente = order.partner_id.name if order.partner_id else "Consumidor Final"
        cliente_doc = (
            order.partner_id.vat
            if order.partner_id and order.partner_id.vat
            else "00000000"
        )
        cliente_tipo_doc = "6" if tipo == "01" else "1"

        valid_lines = order.lines.filtered(lambda l: l.qty and l.price_subtotal_incl)

        total = SunatUBLBuilder._money(sum(valid_lines.mapped("price_subtotal_incl")))
        subtotal = SunatUBLBuilder._money(sum(valid_lines.mapped("price_subtotal")))
        igv = SunatUBLBuilder._money(total - subtotal)

        invoice_lines_xml = SunatUBLBuilder._build_invoice_lines(order)

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
            xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
            xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
            xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2">
    <ext:UBLExtensions>
        <ext:UBLExtension>
            <ext:ExtensionContent/>
        </ext:UBLExtension>
    </ext:UBLExtensions>

    <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
    <cbc:CustomizationID>2.0</cbc:CustomizationID>
    <cbc:ProfileID>0101</cbc:ProfileID>
    <cbc:ID>{serie}-{correlativo}</cbc:ID>
    <cbc:IssueDate>{fields.Date.today()}</cbc:IssueDate>
    <cbc:InvoiceTypeCode listID="0101" listAgencyName="PE:SUNAT" listName="Tipo de Documento" listURI="urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01">{tipo}</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>PEN</cbc:DocumentCurrencyCode>

    <cac:Signature>
    <cbc:ID>{serie}-{correlativo}</cbc:ID>
    <cac:SignatoryParty>
        <cac:PartyIdentification>
            <cbc:ID>{escape(order.company_id.vat or "")}</cbc:ID>
        </cac:PartyIdentification>
        <cac:PartyName>
            <cbc:Name>{escape(order.company_id.name or "")}</cbc:Name>
        </cac:PartyName>
    </cac:SignatoryParty>
    <cac:DigitalSignatureAttachment>
        <cac:ExternalReference>
            <cbc:URI>#signatureKG</cbc:URI>
        </cac:ExternalReference>
    </cac:DigitalSignatureAttachment>
</cac:Signature>

    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="6">{escape(order.company_id.vat or "")}</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyLegalEntity>
                <cbc:RegistrationName>{escape(order.company_id.name or "")}</cbc:RegistrationName>
                <cac:RegistrationAddress>
                    <cbc:AddressTypeCode>0000</cbc:AddressTypeCode>
                </cac:RegistrationAddress>
            </cac:PartyLegalEntity>
        </cac:Party>
    </cac:AccountingSupplierParty>

    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="{cliente_tipo_doc}">{escape(cliente_doc)}</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyLegalEntity>
                <cbc:RegistrationName>{escape(cliente)}</cbc:RegistrationName>
            </cac:PartyLegalEntity>
        </cac:Party>
    </cac:AccountingCustomerParty>

    <cac:PaymentTerms>
    <cbc:ID>FormaPago</cbc:ID>
    <cbc:PaymentMeansID>Contado</cbc:PaymentMeansID>
    </cac:PaymentTerms>

    <cac:TaxTotal>
        <cbc:TaxAmount currencyID="PEN">{igv:.2f}</cbc:TaxAmount>
        <cac:TaxSubtotal>
            <cbc:TaxableAmount currencyID="PEN">{subtotal:.2f}</cbc:TaxableAmount>
            <cbc:TaxAmount currencyID="PEN">{igv:.2f}</cbc:TaxAmount>
            <cac:TaxCategory>
                <cbc:Percent>18.00</cbc:Percent>
                <cbc:TaxExemptionReasonCode>10</cbc:TaxExemptionReasonCode>
                <cac:TaxScheme>
                    <cbc:ID>1000</cbc:ID>
                    <cbc:Name>IGV</cbc:Name>
                    <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
                </cac:TaxScheme>
            </cac:TaxCategory>
        </cac:TaxSubtotal>
    </cac:TaxTotal>

    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="PEN">{subtotal:.2f}</cbc:LineExtensionAmount>
        <cbc:TaxInclusiveAmount currencyID="PEN">{total:.2f}</cbc:TaxInclusiveAmount>
        <cbc:AllowanceTotalAmount currencyID="PEN">0.00</cbc:AllowanceTotalAmount>
        <cbc:ChargeTotalAmount currencyID="PEN">0.00</cbc:ChargeTotalAmount>
        <cbc:PayableAmount currencyID="PEN">{total:.2f}</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
{invoice_lines_xml}
</Invoice>
"""
