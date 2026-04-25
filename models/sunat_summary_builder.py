from odoo import fields
from xml.sax.saxutils import escape


class SunatSummaryBuilder:

    @staticmethod
    def build_rc_xml(order):
        today = fields.Date.today()
        rc_id = f"RC-{today.strftime('%Y%m%d')}-001"

        total = round(order.amount_total, 2)
        subtotal = round(order.amount_total / 1.18, 2)
        igv = round(total - subtotal, 2)

        company_vat = escape(order.company_id.vat or "")
        company_name = escape(order.company_id.name or "")
        if not order.sunat_document_number:
            raise Exception(
                "La boleta no tiene número SUNAT. Reenvía la boleta primero."
            )

        document_number = escape(order.sunat_document_number)

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
<cbc:ReferenceDate>{today}</cbc:ReferenceDate>
<cbc:IssueDate>{today}</cbc:IssueDate>
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
<sac:SummaryDocumentsLine>
<cbc:LineID>1</cbc:LineID>
<cbc:DocumentTypeCode>03</cbc:DocumentTypeCode>
<sac:DocumentSerialID>{document_number.split("-")[0]}</sac:DocumentSerialID>
<sac:StartDocumentNumberID>{document_number.split("-")[1]}</sac:StartDocumentNumberID>
<sac:EndDocumentNumberID>{document_number.split("-")[1]}</sac:EndDocumentNumberID>
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
<cac:TaxScheme>
<cbc:ID>1000</cbc:ID>
<cbc:Name>IGV</cbc:Name>
<cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
</cac:TaxScheme>
</cac:TaxCategory>
</cac:TaxSubtotal>
</cac:TaxTotal>
</sac:SummaryDocumentsLine>
</SummaryDocuments>
"""
        return rc_id, xml
