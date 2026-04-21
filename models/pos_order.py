from odoo import api, fields, models
from odoo.exceptions import UserError
import base64
import zipfile
import io
import requests


class PosOrder(models.Model):
    _inherit = "pos.order"

    sunat_state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("sent", "Enviado"),
            ("accepted", "Aceptado"),
            ("error", "Error"),
        ],
        string="Estado SUNAT",
        default="pending",
        copy=False,
    )

    sunat_document_type = fields.Selection(
        [
            ("01", "Factura"),
            ("03", "Boleta"),
        ],
        string="Tipo de Comprobante",
        compute="_compute_sunat_document_type",
        store=True,
    )

    sunat_document_number = fields.Char(string="Número SUNAT", copy=False)
    sunat_sequence_number = fields.Integer(string="Correlativo SUNAT", copy=False)
    sunat_message = fields.Char(string="Mensaje SUNAT", copy=False)
    sunat_xml = fields.Text(string="XML SUNAT", copy=False)
    sunat_cdr = fields.Text(string="CDR SUNAT", copy=False)
    sunat_xml_filename = fields.Char(string="Nombre XML SUNAT", copy=False)
    sunat_xml_file = fields.Binary(string="Archivo XML SUNAT", copy=False)
    sunat_zip_filename = fields.Char(string="Nombre ZIP SUNAT", copy=False)
    sunat_zip_file = fields.Binary(string="Archivo ZIP SUNAT", copy=False)
    sunat_summary_xml = fields.Text(string="XML Resumen SUNAT", copy=False)
    sunat_summary_filename = fields.Char(string="Nombre Resumen SUNAT", copy=False)
    sunat_summary_file = fields.Binary(string="Archivo Resumen SUNAT", copy=False)
    sunat_summary_ticket = fields.Char(string="Ticket Resumen SUNAT", copy=False)
    sunat_summary_sent = fields.Boolean(
        string="Incluida en Resumen", default=False, copy=False
    )
    sunat_summary_id = fields.Char(string="Resumen SUNAT", copy=False)

    @api.depends("partner_id.vat")
    def _compute_sunat_document_type(self):
        for order in self:
            partner = order.partner_id
            vat = (partner.vat or "").strip() if partner else ""

            if vat.isdigit() and len(vat) == 11:
                order.sunat_document_type = "01"  # Factura
            else:
                order.sunat_document_type = "03"  # Boleta

    def action_generate_sunat_xml(self):
        for order in self:

            partner = order.partner_id
            company = order.company_id

            company_ruc = company.vat or "00000000000"
            company_name = company.name or "EMPRESA"

            customer_doc = partner.vat or "00000000"
            customer_name = partner.name or "Cliente"

            if order.sunat_document_type == "01":
                customer_doc_type = "6"
            else:
                customer_doc_type = "1"

            # Serie y correlativo
            serie, numero = order._get_sunat_series_and_number()
            doc_id = f"{serie}-{numero}"

            order.sunat_sequence_number = numero
            order.sunat_document_number = doc_id

            total_igv = 0.0
            total_valor_venta = 0.0
            lines_xml = ""

            for i, line in enumerate(order.lines, start=1):

                qty = line.qty
                subtotal = round(line.price_subtotal, 2)
                total = round(line.price_subtotal_incl, 2)

                igv = round(total - subtotal, 2)
                price_unit = round(total / qty, 2) if qty else 0.0
                valor_unitario = round(subtotal / qty, 2) if qty else 0.0

                total_igv += igv
                total_valor_venta += subtotal

            lines_xml += f"""
    <cac:InvoiceLine>
        <cbc:ID>{i}</cbc:ID>
        <cbc:InvoicedQuantity unitCode="NIU">{qty}</cbc:InvoicedQuantity>
        <cbc:LineExtensionAmount currencyID="PEN">{subtotal}</cbc:LineExtensionAmount>

        <cac:PricingReference>
            <cac:AlternativeConditionPrice>
                <cbc:PriceAmount currencyID="PEN">{price_unit}</cbc:PriceAmount>
                <cbc:PriceTypeCode>01</cbc:PriceTypeCode>
            </cac:AlternativeConditionPrice>
        </cac:PricingReference>

        <cac:TaxTotal>
            <cbc:TaxAmount currencyID="PEN">{igv}</cbc:TaxAmount>
            <cac:TaxSubtotal>
                <cbc:TaxAmount currencyID="PEN">{igv}</cbc:TaxAmount>
                <cac:TaxCategory>
                    <cbc:ID>10</cbc:ID>
                    <cbc:Percent>18.00</cbc:Percent>
                    <cac:TaxScheme>
                        <cbc:ID>1000</cbc:ID>
                        <cbc:Name>IGV</cbc:Name>
                        <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
                    </cac:TaxScheme>
                </cac:TaxCategory>
            </cac:TaxSubtotal>
        </cac:TaxTotal>

        <cac:Item>
            <cbc:Description>{line.product_id.name}</cbc:Description>
        </cac:Item>

        <cac:Price>
            <cbc:PriceAmount currencyID="PEN">{valor_unitario}</cbc:PriceAmount>
        </cac:Price>
    </cac:InvoiceLine>
"""

        total_igv = round(total_igv, 2)
        total_valor_venta = round(total_valor_venta, 2)
        total_pagar = round(order.amount_total, 2)

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
        xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
        xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
        xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
        xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2">

    <ext:UBLExtensions>
        <ext:UBLExtension>
            <ext:ExtensionContent>
            </ext:ExtensionContent>
        </ext:UBLExtension>
    </ext:UBLExtensions>

    <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
    <cbc:CustomizationID>2.0</cbc:CustomizationID>
    <cbc:ID>{doc_id}</cbc:ID>
    <cbc:IssueDate>{order.date_order.date()}</cbc:IssueDate>
    <cbc:InvoiceTypeCode>{order.sunat_document_type}</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>PEN</cbc:DocumentCurrencyCode>
    <cbc:LineCountNumeric>{len(order.lines)}</cbc:LineCountNumeric>

        <cac:Signature>
        <cbc:ID>{doc_id}</cbc:ID>
        <cac:SignatoryParty>
            <cac:PartyIdentification>
                <cbc:ID>{company_ruc}</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyName>
                <cbc:Name>{company_name}</cbc:Name>
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
                <cbc:ID schemeID="6">{company_ruc}</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyLegalEntity>
                <cbc:RegistrationName>{company_name}</cbc:RegistrationName>
            </cac:PartyLegalEntity>
        </cac:Party>
    </cac:AccountingSupplierParty>

    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="{customer_doc_type}">{customer_doc}</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyLegalEntity>
                <cbc:RegistrationName>{customer_name}</cbc:RegistrationName>
            </cac:PartyLegalEntity>
        </cac:Party>
    </cac:AccountingCustomerParty>

    <cac:TaxTotal>
        <cbc:TaxAmount currencyID="PEN">{total_igv}</cbc:TaxAmount>
        <cac:TaxSubtotal>
            <cbc:TaxAmount currencyID="PEN">{total_igv}</cbc:TaxAmount>
            <cac:TaxCategory>
                <cbc:ID>10</cbc:ID>
                <cbc:Percent>18.00</cbc:Percent>
                <cac:TaxScheme>
                    <cbc:ID>1000</cbc:ID>
                    <cbc:Name>IGV</cbc:Name>
                    <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
                </cac:TaxScheme>
            </cac:TaxCategory>
        </cac:TaxSubtotal>
    </cac:TaxTotal>

    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="PEN">{total_valor_venta}</cbc:LineExtensionAmount>
        <cbc:PayableAmount currencyID="PEN">{total_pagar}</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>

{lines_xml}
</Invoice>
"""
        xml_signed = order._sign_xml_dummy(xml)

        order.sunat_xml = xml_signed
        order.sunat_xml_filename = f"{doc_id}.xml"
        order.sunat_xml_file = base64.b64encode(xml_signed.encode("utf-8"))

        # Crear ZIP en memoria
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(f"{doc_id}.xml", xml_signed)
        zip_buffer.seek(0)

        order.sunat_zip_filename = f"{doc_id}.zip"
        order.sunat_zip_file = base64.b64encode(zip_buffer.read())

        order.sunat_state = "pending"

    def _get_sunat_series_and_number(self):
        self.ensure_one()

        pos_config = self.session_id.config_id

        if self.sunat_document_type == "01":
            serie = pos_config.sunat_serie_factura
        else:
            serie = pos_config.sunat_serie_boleta

        if not serie:
            raise UserError("Falta configurar la serie  SUNAT en este POS.")

        domain = [
            ("id", "!=", self.id),
            ("sunat_document_type", "=", self.sunat_document_type),
            ("session_id.config_id", "=", self.session_id.config_id.id),
            ("sunat_sequence_number", ">", 0),
        ]

        last_order = self.search(domain, order="sunat_sequence_number desc", limit=1)
        next_number = (last_order.sunat_sequence_number or 0) + 1

        return serie, next_number

    def _sign_xml_dummy(self, xml):
        """
        Simulación de firma (solo para pruebas)
        """
        signature = """
    <ds:Signature Id="signatureKG">
        <ds:SignedInfo>
            <ds:CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
            <ds:SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>
        </ds:SignedInfo>
        <ds:SignatureValue>SIMULATED_SIGNATURE</ds:SignatureValue>
    </ds:Signature>
    """

        return xml.replace(
            "<ext:ExtensionContent>", f"<ext:ExtensionContent>{signature}"
        )

    def action_send_sunat(self):
        for order in self:

            if not order.sunat_zip_file:
                raise UserError("Primero genera el XML y ZIP.")

            zip_content = base64.b64decode(order.sunat_zip_file)

            username = order.company_id.vat + order.session_id.config_id.sunat_user
            password = order.session_id.config_id.sunat_password

            url = "https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService"

            soap_xml = f"""
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                xmlns:ser="http://service.sunat.gob.pe">
        <soapenv:Header/>
        <soapenv:Body>
            <ser:sendBill>
                <fileName>{order.sunat_zip_filename}</fileName>
                <contentFile>{base64.b64encode(zip_content).decode()}</contentFile>
            </ser:sendBill>
        </soapenv:Body>
    </soapenv:Envelope>
    """

            response = requests.post(
                url,
                data=soap_xml,
                headers={"Content-Type": "text/xml"},
                auth=(username, password),
            )

            if response.status_code == 200:
                order.sunat_state = "sent"
            else:
                order.sunat_state = "error"

            order.sunat_message = response.text

    def action_generate_summary_rc(self):
        orders = self.search(
            [
                ("sunat_document_type", "=", "03"),
                ("sunat_state", "=", "pending"),
                ("sunat_summary_sent", "=", False),
            ]
        )

        if not orders:
            raise UserError("No hay boletas pendientes para el resumen diario.")

        today = fields.Date.today()
        fecha_emision = today.strftime("%Y-%m-%d")
        fecha_id = today.strftime("%Y%m%d")

        company = self.env.company
        company_ruc = company.vat or "00000000000"
        company_name = company.name or "EMPRESA"

        # Correlativo simple del resumen
        summary_id = f"RC-{fecha_id}-1"
        file_name = f"{company_ruc}-{summary_id}"

        total_importe = 0.0
        total_igv = 0.0
        lines_xml = ""

        for i, order in enumerate(orders, start=1):
            total = round(order.amount_total, 2)
            gravada = round(sum(order.lines.mapped("price_subtotal")), 2)
            igv = round(sum(order.lines.mapped("price_subtotal_incl")) - gravada, 2)

            total_importe += total
            total_igv += igv

            numero = order.sunat_document_number or f"BBB1-{i}"

            parts = numero.split("-")
            serie = parts[0] if len(parts) > 0 else "BBB1"
            correlativo = parts[1] if len(parts) > 1 else str(i)

            lines_xml += f"""
        <sac:SummaryDocumentsLine>
            <cbc:LineID>{i}</cbc:LineID>
            <cbc:DocumentTypeCode>03</cbc:DocumentTypeCode>
            <cbc:ID>{serie}</cbc:ID>
            <cbc:StartDocumentNumberID>{correlativo}</cbc:StartDocumentNumberID>
            <cbc:EndDocumentNumberID>{correlativo}</cbc:EndDocumentNumberID>

            <sac:TotalAmount currencyID="PEN">{total}</sac:TotalAmount>

            <sac:BillingPayment>
                <cbc:PaidAmount currencyID="PEN">{gravada}</cbc:PaidAmount>
                <cbc:InstructionID>01</cbc:InstructionID>
            </sac:BillingPayment>

            <cac:TaxTotal>
                <cbc:TaxAmount currencyID="PEN">{igv}</cbc:TaxAmount>
                <cac:TaxSubtotal>
                    <cbc:TaxAmount currencyID="PEN">{igv}</cbc:TaxAmount>
                    <cac:TaxCategory>
                        <cac:TaxScheme>
                            <cbc:ID>1000</cbc:ID>
                            <cbc:Name>IGV</cbc:Name>
                            <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
                        </cac:TaxScheme>
                    </cac:TaxCategory>
                </cac:TaxSubtotal>
            </cac:TaxTotal>

            <sac:Status>
                <cbc:ConditionCode>1</cbc:ConditionCode>
            </sac:Status>
        </sac:SummaryDocumentsLine>
    """

        total_importe = round(total_importe, 2)
        total_igv = round(total_igv, 2)

        summary_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <SummaryDocuments               xmlns="urn:sunat:names:specification:ubl:peru:schema:xsd:SummaryDocuments-1"
        xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
        xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
        xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
        xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
        xmlns:sac="urn:sunat:names:specification:ubl:peru:schema:xsd:SunatAggregateComponents-1">

        <ext:UBLExtensions>
            <ext:UBLExtension>
                <ext:ExtensionContent>
                </ext:ExtensionContent>
            </ext:UBLExtension>
        </ext:UBLExtensions>

        <cbc:UBLVersionID>2.0</cbc:UBLVersionID>
        <cbc:CustomizationID>1.1</cbc:CustomizationID>
        <cbc:ID>{summary_id}</cbc:ID>
        <cbc:ReferenceDate>{fecha_emision}</cbc:ReferenceDate>
        <cbc:IssueDate>{fecha_emision}</cbc:IssueDate>

        <cac:Signature>
            <cbc:ID>{file_name}</cbc:ID>
            <cac:SignatoryParty>
                    <cac:PartyIdentification>
                    <cbc:ID>{company_ruc}</cbc:ID>
                </cac:PartyIdentification>
                <cac:PartyName>
                    <cbc:Name>{company_name}</cbc:Name>
                </cac:PartyName>
            </cac:SignatoryParty>
            <cac:DigitalSignatureAttachment>
                <cac:ExternalReference>
                    <cbc:URI>#signatureKG</cbc:URI>
                </cac:ExternalReference>
            </cac:DigitalSignatureAttachment>
        </cac:Signature>

        <cac:AccountingSupplierParty>
            <cbc:CustomerAssignedAccountID>{company_ruc}</cbc:CustomerAssignedAccountID>
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

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(f"{file_name}.xml", summary_xml)

        zip_buffer.seek(0)

        summary_file_data = base64.b64encode(zip_buffer.read())

        orders.write(
            {
                "sunat_summary_sent": True,
                "sunat_summary_id": summary_id,
                "sunat_summary_filename": f"{file_name}.zip",
                "sunat_summary_file": summary_file_data,
                "sunat_summary_xml": summary_xml,
            }
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Resumen diario generado",
                "message": f"Se generó el resumen {summary_id} con {len(orders)} boleta(s).",
                "type": "success",
                "sticky": False,
            },
        }

    def action_assign_sunat_number(self):
        for order in self:

            if order.sunat_document_number:
                continue  # ya tiene número

            serie, numero = order._get_sunat_series_and_number()

            doc_id = f"{serie}-{numero}"

            order.sunat_sequence_number = numero
            order.sunat_document_number = doc_id
            order.sunat_state = "pending"

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()

        for order in self:
            try:
                # Si es boleta, solo asigna número y queda pendiente
                if order.sunat_document_type == "03":
                    order.action_assign_sunat_number()
                    order.sunat_state = "pending"

                # Si es factura, generar XML/ZIP y enviar automáticamente
                elif order.sunat_document_type == "01":
                    order.action_assign_sunat_number()
                    order.action_generate_sunat_xml()
                    order.action_send_sunat()

            except Exception as e:
                # No rompas la venta, solo registra el error
                order.sunat_state = "error"
                order.sunat_message = str(e)

        return res
