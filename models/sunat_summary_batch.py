from odoo import models, fields
from .sunat_summary_builder import SunatSummaryBuilder
from .sunat_signer import SunatSigner
from .sunat_client import SunatClient

import base64
import io
import zipfile
import re


class SunatSummaryBatch(models.Model):
    _name = "sunat.summary.batch"
    _description = "Resumen Diario SUNAT RC"

    name = fields.Char(string="Nombre RC", readonly=True)
    date = fields.Date(
        string="Fecha",
        default=fields.Date.context_today,
        required=True,
    )

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("generated", "Generado"),
            ("sent", "Enviado"),
            ("accepted", "Aceptado"),
            ("error", "Error"),
        ],
        string="Estado",
        default="draft",
        readonly=True,
    )

    order_ids = fields.Many2many(
        "pos.order",
        string="Boletas incluidas",
    )

    xml_file = fields.Binary(string="Archivo XML", readonly=True)
    xml_filename = fields.Char(string="Nombre XML", readonly=True)

    zip_file = fields.Binary(string="Archivo ZIP", readonly=True)
    zip_filename = fields.Char(string="Nombre ZIP", readonly=True)

    ticket = fields.Char(string="Ticket SUNAT", readonly=True)
    response_message = fields.Text(string="Respuesta SUNAT", readonly=True)

    def action_load_pending_boletas(self):
        for batch in self:
            orders = self.env["pos.order"].search(
                [
                    ("sunat_state", "=", "pendiente_resumen"),
                    ("sunat_document_type", "=", "03"),
                    ("sunat_rc_batch_id", "=", False),
                ],
                order="sunat_document_number asc",
            )

            batch.order_ids = [(6, 0, orders.ids)]

        return True

    def action_send_summary(self):
        for batch in self:

            if not batch.order_ids:
                batch.write(
                    {
                        "state": "error",
                        "response_message": "No hay boletas incluidas en este resumen.",
                    }
                )
                continue

            try:
                rc_id, rc_xml = SunatSummaryBuilder.build_rc_xml(batch.order_ids)

                first_order = batch.order_ids[0]
                cfg = first_order.session_id.config_id.sudo()
                company_vat = first_order.company_id.vat

                signed_xml = SunatSigner.sign_xml(
                    rc_xml,
                    cfg.sunat_certificate_path,
                    cfg.sunat_certificate_password,
                )

                zip_name = f"{company_vat}-{rc_id}.zip"
                xml_name = f"{company_vat}-{rc_id}.xml"

                mem_zip = io.BytesIO()

                with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(xml_name, signed_xml)

                zip_binary = base64.b64encode(mem_zip.getvalue())

                username = f"{company_vat}{cfg.sunat_user}"

                status_code, response = SunatClient.send_summary(
                    cfg.sunat_mode,
                    username,
                    cfg.sunat_password,
                    zip_name,
                    zip_binary.decode(),
                )

                match = re.search(
                    r"<(?:\w+:)?ticket>(.*?)</(?:\w+:)?ticket>",
                    response,
                )

                if not match and "ya fue presentado anteriormente" in response:
                    m = re.search(r"valor:\s*'([^']+)'", response)
                    if m:
                        match = m

                if not match:
                    batch.write(
                        {
                            "name": rc_id,
                            "state": "error",
                            "xml_file": base64.b64encode(signed_xml.encode("utf-8")),
                            "xml_filename": xml_name,
                            "zip_file": zip_binary,
                            "zip_filename": zip_name,
                            "response_message": f"HTTP {status_code}\n{response[:3000]}",
                        }
                    )
                    continue

                ticket = match.group(1)

                batch.write(
                    {
                        "name": rc_id,
                        "ticket": ticket,
                        "state": "sent",
                        "xml_file": base64.b64encode(signed_xml.encode("utf-8")),
                        "xml_filename": xml_name,
                        "zip_file": zip_binary,
                        "zip_filename": zip_name,
                        "response_message": "Resumen RC enviado. Ticket SUNAT recibido.",
                    }
                )

                batch.order_ids.write(
                    {
                        "sunat_state": "rc_enviado",
                        "sunat_summary_id": ticket,
                        "sunat_message": f"Incluido en Resumen Diario RC {rc_id}. "
                        f"Ticket SUNAT: {ticket}",
                        "sunat_rc_batch_id": batch.id,
                    }
                )

            except Exception as e:
                batch.write(
                    {
                        "state": "error",
                        "response_message": f"Error enviando RC: {str(e)}",
                    }
                )

        return True

    def action_check_ticket(self):
        for batch in self:

            if not batch.ticket:
                raise Exception("No existe ticket para consultar.")

            first_order = batch.order_ids[0]
            cfg = first_order.session_id.config_id.sudo()

            username = f"{first_order.company_id.vat}" f"{cfg.sunat_user}"

            status_code, response = SunatClient.get_status(
                cfg.sunat_mode,
                username,
                cfg.sunat_password,
                batch.ticket,
            )

            if "<statusCode>0</statusCode>" in response:

                batch.write(
                    {
                        "state": "accepted",
                        "response_message": f"Resumen Diario aceptado por SUNAT. "
                        f"Ticket {batch.ticket}",
                    }
                )

                batch.order_ids.write(
                    {
                        "sunat_state": "aceptado",
                        "sunat_message": f"Aceptado vía Resumen Diario. "
                        f"Ticket {batch.ticket}",
                    }
                )

            else:
                batch.write({"response_message": f"Respuesta SUNAT: {response[:500]}"})

        return True
