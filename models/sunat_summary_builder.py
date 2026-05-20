from odoo import fields
from xml.sax.saxutils import escape
import pytz


class SunatSummaryBuilder:

    @staticmethod
    def build_rc_xml(orders):
        if not orders:
            raise Exception("No hay boletas para generar el resumen RC.")

        env = orders.env

        # Fecha real de las boletas incluidas
        tz_pe = pytz.timezone("America/Lima")

        order_dates = []

        for o in orders:
            dt = fields.Datetime.to_datetime(o.date_order)

            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)

            order_dates.append(dt.astimezone(tz_pe).date())

        if not order_dates:
            raise Exception("No se pudo determinar la fecha de las boletas.")

        reference_date = min(order_dates)

        # Seguridad: no mezclar boletas de días distintos en el mismo RC
        if any(d != reference_date for d in order_dates):
            raise Exception(
                "No puedes generar un mismo Resumen Diario con boletas de fechas distintas."
            )

        # Fecha de emisión del resumen.
        issue_date = reference_date

        prefix = f"RC-{reference_date.strftime('%Y%m%d')}-"

        last_batch = env["sunat.summary.batch"].search(
            [("name", "like", prefix)],
            order="name desc",
            limit=1,
        )

        sequence = 1

        if last_batch and last_batch.name:
            try:
                sequence = int(last_batch.name.split("-")[-1]) + 1
            except Exception:
                sequence = 1

        rc_id = f"{prefix}{sequence:03d}"

        first_order = orders[0]
        company_vat = escape(first_order.company_id.vat or "")
        company_name = escape(first_order.company_id.name or "")

        lines_xml = ""

        for i, order in enumerate(orders, start=1):
            if not order.sunat_document_number:
                raise Exception(f"La boleta {order.name} no tiene número SUNAT.")

            # --- CORRECCIÓN DE REDONDEO ---
            total = round(order.amount_total, 2)
            subtotal = round(total / 1.18, 2)
            igv = round(total - subtotal, 2)

            document_number = escape(order.sunat_document_number)
            serie, correlativo = document_number.split("-")

            # --- CORRECCIÓN DE CLIENTES VARIOS (DNI 00000000) ---
            partner = order.partner_id
            vat_clean = partner.vat.strip() if partner and partner.vat else ""

            if vat_clean and vat_clean != "00000000":
                client_doc = escape(vat_clean)
                client_doc_type = (
                    "1" if len(vat_clean) == 8 else "6" if len(vat_clean) == 11 else "0"
                )
            else:
                # Si no hay cliente o es el comodín 00000000, se reporta como "Otros" sin documento
                client_doc = "-"
                client_doc_type = "0"

            lines_xml += f"""
<sac:SummaryDocumentsLine>
<cbc:LineID>{i}</cbc:LineID>
<cbc:DocumentTypeCode>03</cbc:DocumentTypeCode>
<cbc:ID>{serie}-{correlativo}</cbc:ID>

<cac:AccountingCustomerParty>
<cbc:CustomerAssignedAccountID>{client_doc}</cbc:CustomerAssignedAccountID>
<cbc:AdditionalAccountID>{client_doc_type}</cbc:AdditionalAccountID>
</cac:AccountingCustomerParty>

<cac:Status>
<cbc:ConditionCode>1</cbc:ConditionCode>
</cac:Status>

<sac:TotalAmount currencyID="PEN">{total:.2f}</sac:TotalAmount>

<sac:BillingPayment>
<cbc:PaidAmount currencyID="PEN">{subtotal:.2f}</cbc:PaidAmount>
<cbc:InstructionID>01</cbc:InstructionID>
</sac:BillingPayment>

<cac:TaxTotal>
<cbc:TaxAmount currencyID="PEN">{igv:.2f}</cbc:TaxAmount>
<cac:TaxSubtotal>
<cbc:TaxableAmount currencyID="PEN">{subtotal:.2f}</cbc:TaxableAmount>
<cbc:TaxAmount currencyID="PEN">{igv:.2f}</cbc:TaxAmount>
<cac:TaxCategory>
<cbc:ID>S</cbc:ID>
<cbc:Percent>18.00</cbc:Percent>
<cac:TaxScheme>
<cbc:ID>1000</cbc:ID>
<cbc:Name>IGV</cbc:Name>
<cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
</cac:TaxScheme>
</cac:TaxCategory>
</cac:TaxSubtotal>
</cac:TaxTotal>

</sac:SummaryDocumentsLine>
"""

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<SummaryDocuments
xmlns="urn:sunat:names:specification:ubl:peru:schema:xsd:SummaryDocuments-1"
xmlns:sac="urn:sunat:names:specification:ubl:peru:schema:xsd:SunatAggregateComponents-1"
xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2">
<ext:UBLExtensions>
<ext:UBLExtension>
<ext:ExtensionContent/>
</ext:UBLExtension>
</ext:UBLExtensions>
<cbc:UBLVersionID>2.0</cbc:UBLVersionID>
<cbc:CustomizationID>1.1</cbc:CustomizationID>
<cbc:ID>{rc_id}</cbc:ID>
<cbc:ReferenceDate>{reference_date}</cbc:ReferenceDate>
<cbc:IssueDate>{issue_date}</cbc:IssueDate>
<cac:Signature>
<cbc:ID>{rc_id}</cbc:ID>
<cac:SignatoryParty>
<cac:PartyIdentification>
<cbc:ID>{company_vat}</cbc:ID>
</cac:PartyIdentification>
<cac:PartyName>
<cbc:Name>{company_name}</cbc:Name>
</cac:PartyName>
</cac:SignatoryParty>
<cac:DigitalSignatureAttachment>
<cac:ExternalReference>
<cbc:URI>#{rc_id}</cbc:URI>
</cac:ExternalReference>
</cac:DigitalSignatureAttachment>
</cac:Signature>
<cac:AccountingSupplierParty>
<cbc:CustomerAssignedAccountID>{company_vat}</cbc:CustomerAssignedAccountID>
<cbc:AdditionalAccountID>6</cbc:AdditionalAccountID>
<cac:Party>
<cac:PartyLegalEntity>
<cbc:RegistrationName>{company_name}</cbc:RegistrationName>
</cac:PartyLegalEntity>
</cac:Party>
</cac:AccountingSupplierParty>
{lines_xml}
</SummaryDocuments>
"""
        return rc_id, xml
