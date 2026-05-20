from odoo import models, fields
from .sunat_summary_builder import SunatSummaryBuilder
from .sunat_signer import SunatSigner
from .sunat_client import SunatClient

import base64
import io
import zipfile
import re
import xml.etree.ElementTree as ET


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
                    m = re.search(r"ticket:\s*([^,]+)", response)

                    if not m:
                        m = re.search(r"valor:\s*\"([^\"]+)\"", response)

                    if not m:
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
                batch.write(
                    {
                        "response_message": "No existe ticket para consultar.",
                    }
                )
                continue

            if not batch.order_ids:
                batch.write(
                    {
                        "response_message": "El resumen no tiene órdenes asociadas.",
                    }
                )
                continue

            first_order = batch.order_ids[0]
            cfg = first_order.session_id.config_id.sudo()
            username = f"{first_order.company_id.vat}{cfg.sunat_user}"

            try:
                status_code, response = SunatClient.get_status(
                    cfg.sunat_mode,
                    username,
                    cfg.sunat_password,
                    batch.ticket,
                )

                batch.write(
                    {
                        "response_message": f"HTTP {status_code}\n{response[:3000]}",
                    }
                )

                # 1. Primero buscar CDR en <content>.
                # SUNAT puede devolver statusCode 99 junto con content,
                # y ese content es lo que realmente debemos leer.
                content_match = re.search(
                    r"<(?:\w+:)?content>(.*?)</(?:\w+:)?content>",
                    response,
                    re.DOTALL,
                )

                if content_match:
                    cdr_zip_base64 = content_match.group(1).strip()
                    cdr_zip_bytes = base64.b64decode(cdr_zip_base64)

                    with zipfile.ZipFile(io.BytesIO(cdr_zip_bytes), "r") as zf:
                        xml_names = [
                            n for n in zf.namelist() if n.lower().endswith(".xml")
                        ]

                        if not xml_names:
                            raise Exception("El CDR ZIP no contiene XML.")

                        cdr_xml = zf.read(xml_names[0])
                        root = ET.fromstring(cdr_xml)

                        response_code_node = root.find(".//{*}ResponseCode")
                        description_node = root.find(".//{*}Description")

                        cdr_code = (
                            response_code_node.text
                            if response_code_node is not None
                            else ""
                        )
                        cdr_description = (
                            description_node.text
                            if description_node is not None
                            else ""
                        )

                    if cdr_code == "0":
                        batch.write(
                            {
                                "state": "accepted",
                                "response_message": (
                                    f"Código CDR: {cdr_code}\n{cdr_description}"
                                ),
                            }
                        )

                        batch.order_ids.write(
                            {
                                "sunat_state": "aceptado",
                                "sunat_message": (
                                    f"Aceptado vía Resumen Diario {batch.name}. "
                                    f"Código CDR: {cdr_code} - {cdr_description}"
                                ),
                            }
                        )

                    else:
                        batch.write(
                            {
                                "state": "error",
                                "response_message": (
                                    f"Código CDR: {cdr_code}\n{cdr_description}"
                                ),
                            }
                        )

                        batch.order_ids.write(
                            {
                                "sunat_state": "error",
                                "sunat_message": (
                                    f"RC {batch.name} rechazado. "
                                    f"Código CDR: {cdr_code} - {cdr_description}"
                                ),
                            }
                        )

                    continue

                # 2. Si NO hay content, recién revisar statusCode.
                status_match = re.search(
                    r"<(?:\w+:)?statusCode>(.*?)</(?:\w+:)?statusCode>",
                    response,
                    re.DOTALL,
                )

                if status_match:
                    status_code_sunat = status_match.group(1).strip()

                    if status_code_sunat in ("98", "99"):
                        batch.write(
                            {
                                "state": "sent",
                                "response_message": (
                                    f"SUNAT aún está procesando el ticket {batch.ticket}. "
                                    f"Código estado SUNAT: {status_code_sunat}. "
                                    "Volver a consultar en unos minutos.\n\n"
                                    f"{response[:3000]}"
                                ),
                            }
                        )
                        continue

                    desc_match = re.search(
                        r"<(?:\w+:)?statusMessage>(.*?)</(?:\w+:)?statusMessage>",
                        response,
                        re.DOTALL,
                    )

                    desc = (
                        desc_match.group(1).strip() if desc_match else response[:1000]
                    )

                    batch.write(
                        {
                            "state": "sent",
                            "response_message": (
                                f"SUNAT respondió con estado {status_code_sunat}. "
                                "No se marcará como error automático. "
                                "Volver a consultar el ticket.\n\n"
                                f"{response[:3000]}"
                            ),
                        }
                    )
                    continue

                # 3. Si no hay content ni statusCode, guardar respuesta para revisión.
                batch.write(
                    {
                        "state": "sent",
                        "response_message": (
                            "SUNAT respondió, pero no se encontró CDR ni statusCode. "
                            "Volver a consultar o revisar respuesta:\n\n"
                            f"{response[:3000]}"
                        ),
                    }
                )

            except Exception as e:
                batch.write(
                    {
                        "state": "sent",
                        "response_message": (
                            f"No se pudo consultar/procesar el ticket {batch.ticket}. "
                            f"Se puede volver a intentar.\n\nError: {str(e)}"
                        ),
                    }
                )

        return True
