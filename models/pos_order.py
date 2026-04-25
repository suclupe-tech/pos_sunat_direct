import sys
import re

from soupsieve import match

sys.path.insert(0, r"C:\odoo_libs")
from odoo import models, fields
import base64
import io
import zipfile
import requests
from lxml import etree
from signxml import XMLSigner, methods
from cryptography.hazmat.primitives.serialization import (
    pkcs12,
    Encoding,
    PrivateFormat,
    NoEncryption,
)
from xml.sax.saxutils import escape
from decimal import Decimal, ROUND_HALF_UP


class PosOrder(models.Model):
    _inherit = "pos.order"

    sunat_state = fields.Char(string="Estado SUNAT", readonly=True)
    sunat_document_type = fields.Char(string="Tipo Documento SUNAT", readonly=True)
    sunat_document_number = fields.Char(string="Número Documento SUNAT", readonly=True)
    sunat_message = fields.Text(string="Mensaje SUNAT", readonly=True)

    sunat_xml = fields.Text(string="XML SUNAT")
    sunat_xml_filename = fields.Char(string="Nombre XML", readonly=True)
    sunat_xml_file = fields.Binary(string="Archivo XML", readonly=True)

    sunat_zip_filename = fields.Char(string="Nombre ZIP", readonly=True)
    sunat_zip_file = fields.Binary(string="Archivo ZIP", readonly=True)

    sunat_cdr_filename = fields.Char(string="Nombre CDR", readonly=True)
    sunat_cdr_file = fields.Binary(string="Archivo CDR", readonly=True)

    sunat_summary_filename = fields.Char(string="Nombre Resumen", readonly=True)
    sunat_summary_file = fields.Binary(string="Archivo Resumen", readonly=True)
    sunat_summary_xml = fields.Text(string="XML Resumen")
    sunat_summary_id = fields.Char(string="ID Resumen", readonly=True)

    def action_generate_sunat_xml(self):
        for order in self:
            config = order.session_id.config_id

        tipo = (
            "01"
            if order.partner_id
            and order.partner_id.vat
            and len(order.partner_id.vat.strip()) == 11
            else "03"
        )

        serie = (
            config.sunat_serie_factura if tipo == "01" else config.sunat_serie_boleta
        )
        correlativo = str(order.id).zfill(8)

        cliente = order.partner_id.name if order.partner_id else "Consumidor Final"
        cliente_doc = (
            order.partner_id.vat
            if order.partner_id and order.partner_id.vat
            else "00000000"
        )
        cliente_tipo_doc = "6" if tipo == "01" else "1"

        nombre_cpe = f"{order.company_id.vat}-{tipo}-{serie}-{correlativo}"

        total = Decimal(str(order.amount_total)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        subtotal = (total / Decimal("1.18")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        igv = (total - subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        xml_demo = f"""<?xml version="1.0" encoding="UTF-8"?>
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
    <cbc:ProfileID schemeName="SUNAT:Identificador de Tipo de Operación" schemeAgencyName="PE:SUNAT" schemeURI="urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo51">0101</cbc:ProfileID>
    <cbc:ID>{serie}-{correlativo}</cbc:ID>
    <cbc:IssueDate>{fields.Date.today()}</cbc:IssueDate>
    <cbc:InvoiceTypeCode listID="0101" listAgencyName="PE:SUNAT" listName="Tipo de Documento" listURI="urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01">{tipo}</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>PEN</cbc:DocumentCurrencyCode>

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

    <cac:InvoiceLine>
        <cbc:ID>1</cbc:ID>
        <cbc:InvoicedQuantity unitCode="NIU">1</cbc:InvoicedQuantity>
        <cbc:LineExtensionAmount currencyID="PEN">{subtotal:.2f}</cbc:LineExtensionAmount>

        <cac:PricingReference>
            <cac:AlternativeConditionPrice>
                <cbc:PriceAmount currencyID="PEN">{total:.2f}</cbc:PriceAmount>
                <cbc:PriceTypeCode>01</cbc:PriceTypeCode>
            </cac:AlternativeConditionPrice>
        </cac:PricingReference>

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

        <cac:Item>
            <cbc:Description>VENTA POS</cbc:Description>
        </cac:Item>

        <cac:Price>
            <cbc:PriceAmount currencyID="PEN">{subtotal:.2f}</cbc:PriceAmount>
        </cac:Price>
    </cac:InvoiceLine>
</Invoice>
"""

        with open(config.sunat_certificate_path, "rb") as cert_file:
            pfx_data = cert_file.read()

        private_key, certificate, extra = pkcs12.load_key_and_certificates(
            pfx_data,
            config.sunat_certificate_password.encode(),
        )

        key_pem = private_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.PKCS8,
            NoEncryption(),
        )

        cert_pem = certificate.public_bytes(Encoding.PEM)

        root = etree.fromstring(xml_demo.encode("utf-8"))

        signed_root = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
            c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
        ).sign(
            root,
            key=key_pem,
            cert=cert_pem,
        )

        ns = {
            "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
        }

        signature = signed_root.find(".//ds:Signature", namespaces=ns)
        extension_content = signed_root.find(".//ext:ExtensionContent", namespaces=ns)

        if signature is not None and extension_content is not None:
            signature.getparent().remove(signature)
            extension_content.append(signature)

        xml_firmado = etree.tostring(
            signed_root,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        ).decode("utf-8")

        order.write(
            {
                "sunat_state": "xml_firmado",
                "sunat_document_type": tipo,
                "sunat_document_number": f"{serie}-{correlativo}",
                "sunat_message": "XML UBL firmado correctamente.",
                "sunat_xml": xml_firmado,
                "sunat_xml_filename": f"{nombre_cpe}.xml",
                "sunat_zip_filename": False,
                "sunat_zip_file": False,
            }
        )

        return True

    def action_send_sunat(self):
        for order in self:
            config = order.session_id.config_id

        try:
            # siempre regenerar ZIP con el XML actual
            xml_name = order.sunat_xml_filename
            xml_data = order.sunat_xml or ""

            if not xml_name or not xml_data:
                raise Exception("Primero debes generar el XML SUNAT.")

            mem_zip = io.BytesIO()

            with zipfile.ZipFile(
                mem_zip,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as zf:
                zf.writestr(xml_name, xml_data)

            zip_binary = base64.b64encode(mem_zip.getvalue())
            zip_name = xml_name.replace(".xml", ".zip")

            order.write(
                {
                    "sunat_zip_filename": zip_name,
                    "sunat_zip_file": zip_binary,
                }
            )

            ruc = order.company_id.vat or ""

            if "ProfileID" not in xml_data or 'listID="0101"' not in xml_data:
                order.write(
                    {
                        "sunat_state": "debug_xml",
                        "sunat_message": xml_data[:3000],
                    }
                )
                return True
            if not ruc:
                raise Exception("La empresa no tiene RUC configurado.")

            username = f"{ruc}{config.sunat_user}"
            password = config.sunat_password

            if config.sunat_mode == "beta":
                url = "https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService"
            else:
                url = "https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService"

            zip_base64 = (
                order.sunat_zip_file.decode()
                if isinstance(order.sunat_zip_file, bytes)
                else order.sunat_zip_file
            )

            soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
xmlns:ser="http://service.sunat.gob.pe"
xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
<soapenv:Header>
<wsse:Security>
<wsse:UsernameToken>
<wsse:Username>{username}</wsse:Username>
<wsse:Password>{password}</wsse:Password>
</wsse:UsernameToken>
</wsse:Security>
</soapenv:Header>
<soapenv:Body>
<ser:sendBill>
<fileName>{order.sunat_zip_filename}</fileName>
<contentFile>{zip_base64}</contentFile>
</ser:sendBill>
</soapenv:Body>
</soapenv:Envelope>"""

            headers = {
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "",
            }

            response = requests.post(
                url,
                data=soap_body.encode("utf-8"),
                headers=headers,
                timeout=60,
            )

            match = re.search(
                r"<applicationResponse>(.*?)</applicationResponse>",
                response.text,
            )

            if match:
                cdr_base64 = match.group(1)
                cdr_filename = "R-" + order.sunat_zip_filename

                order.write(
                    {
                        "sunat_state": "cdr_recibido",
                        "sunat_cdr_filename": cdr_filename,
                        "sunat_cdr_file": cdr_base64,
                        "sunat_message": f"CDR recibido correctamente\n"
                        f"Usuario={username}\n"
                        f"Archivo={cdr_filename}",
                    }
                )

            else:
                order.write(
                    {
                        "sunat_state": "respuesta_sunat",
                        "sunat_message": f"HTTP {response.status_code}\n"
                        f"Usuario={username}\n"
                        f"Respuesta:\n{response.text[:2000]}",
                    }
                )

        except Exception as e:
            order.write(
                {
                    "sunat_state": "error",
                    "sunat_message": f"Error envío SUNAT: {str(e)}",
                }
            )

        return True

    def action_generate_summary_rc(self):
        for order in self:
            order.write(
                {
                    "sunat_message": "Resumen RC aún no implementado.",
                }
            )
        return True
