from odoo import models, fields
import base64
import io
import zipfile

from .sunat_ubl_builder import SunatUBLBuilder
from .sunat_signer import SunatSigner
from .sunat_client import SunatClient
from .sunat_cdr import SunatCDR
from .sunat_summary_builder import SunatSummaryBuilder
import re


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

    sunat_cdr_code = fields.Char(string="Código CDR", readonly=True)
    sunat_cdr_description = fields.Text(string="Descripción CDR", readonly=True)

    sunat_summary_filename = fields.Char(string="Nombre Resumen", readonly=True)
    sunat_summary_file = fields.Binary(string="Archivo Resumen", readonly=True)
    sunat_summary_xml = fields.Text(string="XML Resumen")
    sunat_summary_id = fields.Char(string="ID Resumen", readonly=True)

    sunat_rc_batch_id = fields.Many2one(
        "sunat.summary.batch",
        string="Lote RC",
        readonly=True,
    )

    def _get_tipo_doc(self):
        self.ensure_one()
        if (
            self.partner_id
            and self.partner_id.vat
            and len(self.partner_id.vat.strip()) == 11
        ):
            return "01"
        return "03"

    def _get_serie(self, tipo):
        self.ensure_one()
        cfg = self.session_id.config_id
        return cfg.sunat_serie_factura if tipo == "01" else cfg.sunat_serie_boleta

    # OJO:
    # esto luego lo cambiaremos por ir.sequence oficial SUNAT
    def _get_correlativo(self, tipo):
        self.ensure_one()

        sequence_code = "sunat.factura" if tipo == "01" else "sunat.boleta"

        return self.env["ir.sequence"].next_by_code(sequence_code)

    def action_generate_sunat_xml(self):
        for order in self:
            try:
                tipo = order._get_tipo_doc()
                serie = order._get_serie(tipo)
                correlativo = order._get_correlativo(tipo)

                nombre_cpe = (
                    f"{order.company_id.vat}-" f"{tipo}-" f"{serie}-" f"{correlativo}"
                )

                xml = SunatUBLBuilder.build_invoice_xml(
                    order,
                    tipo,
                    serie,
                    correlativo,
                )

                cfg = order.session_id.config_id.sudo()

                xml_signed = SunatSigner.sign_xml(
                    xml,
                    cfg.sunat_certificate_path,
                    cfg.sunat_certificate_password,
                )

                order.write(
                    {
                        "sunat_state": "xml_firmado",
                        "sunat_document_type": tipo,
                        "sunat_document_number": f"{serie}-{correlativo}",
                        "sunat_message": "XML firmado correctamente",
                        "sunat_xml": xml_signed,
                        "sunat_xml_filename": f"{nombre_cpe}.xml",
                        "sunat_xml_file": base64.b64encode(xml_signed.encode("utf-8")),
                        "sunat_zip_filename": False,
                        "sunat_zip_file": False,
                    }
                )

            except Exception as e:
                order.write(
                    {
                        "sunat_state": "error",
                        "sunat_message": f"Error generando XML: {str(e)}",
                    }
                )

        return True

    def action_send_sunat(self):
        for order in self:

            if order.sunat_state == "aceptado":
                order.write(
                    {
                        "sunat_message": "Documento ya fue aceptado por SUNAT. No se reenviará."
                    }
                )
                continue

            try:
                if not order.sunat_xml:
                    raise Exception("Primero genere XML SUNAT")

                mem_zip = io.BytesIO()

                with zipfile.ZipFile(
                    mem_zip,
                    mode="w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as zf:
                    xml_filename = order.sunat_xml_filename

                    if not xml_filename:
                        raise Exception(
                            "El XML no tiene nombre. Primero genera XML SUNAT nuevamente."
                        )

                    zf.writestr(
                        xml_filename,
                        order.sunat_xml,
                    )

                zip_binary = base64.b64encode(mem_zip.getvalue())

                zip_name = xml_filename.replace(
                    ".xml",
                    ".zip",
                )

                order.write(
                    {
                        "sunat_zip_filename": zip_name,
                        "sunat_zip_file": zip_binary,
                    }
                )

                cfg = order.session_id.config_id

                username = f"{order.company_id.vat}{cfg.sunat_user}"

                status_code, response_text = SunatClient.send_bill(
                    cfg.sunat_mode,
                    username,
                    cfg.sunat_password,
                    zip_name,
                    zip_binary.decode(),
                )

                cdr_base64 = SunatCDR.extract_application_response(response_text)

                if not cdr_base64:
                    order.write(
                        {
                            "sunat_state": "respuesta_sunat",
                            "sunat_message": f"HTTP {status_code}\n{response_text[:3000]}",
                        }
                    )
                    continue

                cdr = SunatCDR.parse_cdr(cdr_base64)

                estado = "aceptado" if cdr["code"] == "0" else "observado"

                order.write(
                    {
                        "sunat_state": estado,
                        "sunat_cdr_filename": f"R-{zip_name}",
                        "sunat_cdr_file": cdr_base64,
                        "sunat_cdr_code": cdr["code"],
                        "sunat_cdr_description": cdr["description"],
                        "sunat_message": f"Código={cdr['code']} | "
                        f"{cdr['description']}",
                    }
                )

            except Exception as e:
                order.write(
                    {
                        "sunat_state": "pendiente_envio",
                        "sunat_message": f"Pendiente de envío: {str(e)}",
                    }
                )

        return True

    def action_generate_summary_rc(self):
        for order in self:
            try:
                cfg = order.session_id.config_id

                orders = (
                    order.sunat_rc_batch_id.order_ids
                    if order.sunat_rc_batch_id
                    else order
                )
                rc_id, rc_xml = SunatSummaryBuilder.build_rc_xml(orders)

                rc_signed = SunatSigner.sign_xml(
                    rc_xml,
                    cfg.sunat_certificate_path,
                    cfg.sunat_certificate_password,
                )

                zip_name = f"{order.company_id.vat}-{rc_id}.zip"

                mem_zip = io.BytesIO()

                with zipfile.ZipFile(
                    mem_zip,
                    mode="w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as zf:
                    zf.writestr(
                        f"{order.company_id.vat}-{rc_id}.xml",
                        rc_signed,
                    )

                zip_binary = base64.b64encode(mem_zip.getvalue())

                username = f"{order.company_id.vat}{cfg.sunat_user}"

                status_code, response_text = SunatClient.send_summary(
                    cfg.sunat_mode,
                    username,
                    cfg.sunat_password,
                    zip_name,
                    zip_binary.decode(),
                )

                match = re.search(r"<ticket>(.*?)</ticket>", response_text)

                if not match:
                    raise Exception(f"Sin ticket SUNAT:\n{response_text[:2000]}")

                ticket = match.group(1)

                order.write(
                    {
                        "sunat_summary_id": ticket,
                        "sunat_summary_filename": zip_name,
                        "sunat_summary_file": zip_binary,
                        "sunat_summary_xml": rc_signed,
                        "sunat_state": "rc_enviado",
                        "sunat_message": f"Resumen RC enviado. Ticket={ticket}",
                    }
                )

            except Exception as e:
                order.write(
                    {
                        "sunat_state": "error",
                        "sunat_summary_filename": locals().get("zip_name", ""),
                        "sunat_summary_file": locals().get("zip_binary", False),
                        "sunat_summary_xml": locals().get(
                            "rc_signed", locals().get("rc_xml", "")
                        ),
                        "sunat_message": f"Error Resumen RC: {str(e)}",
                    }
                )

        return True

    def action_send_pending_to_sunat(self):

        pendientes = self.search([("sunat_state", "=", "pendiente_envio")])

        for order in pendientes:
            order.action_send_sunat()

        return True

    def _process_order(self, order, draft):
        pos_order_id = super()._process_order(order, draft)
        pos_order = self.browse(pos_order_id)

        try:
            if pos_order and pos_order.exists():
                tipo = pos_order._get_tipo_doc()

                if tipo == "01":
                    if not pos_order.sunat_xml:
                        pos_order.action_generate_sunat_xml()

                    pos_order.action_send_sunat()

                elif tipo == "03":
                    if not pos_order.sunat_xml:
                        pos_order.action_generate_sunat_xml()

                    pos_order.write(
                        {
                            "sunat_state": "pendiente_resumen",
                            "sunat_message": "Pendiente para envío por Resumen Diario",
                        }
                    )

        except Exception as e:
            if pos_order and pos_order.exists():
                pos_order.write(
                    {
                        "sunat_state": "pendiente_envio",
                        "sunat_message": f"Error auto envío: {str(e)}",
                    }
                )

        return pos_order_id
