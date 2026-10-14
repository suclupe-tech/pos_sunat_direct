from odoo import models, fields, api
import base64
import io
import zipfile

from .sunat_ubl_builder import SunatUBLBuilder
from .sunat_signer import SunatSigner
from .sunat_client import SunatClient
from .sunat_cdr import SunatCDR
from .sunat_summary_builder import SunatSummaryBuilder
import re
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

    sunat_state = fields.Char(string="Estado SUNAT", readonly=True)
    sunat_document_type = fields.Selection(
        [
            ("01", "Factura"),
            ("03", "Boleta"),
            ("07", "Nota de Crédito"),
            ("NV", "Nota de Venta"),
        ],
        string="Tipo Documento SUNAT",
        readonly=False,
        default="03",
    )
    sunat_document_number = fields.Char(string="Número Documento SUNAT", readonly=True)

    sunat_origin_order_id = fields.Many2one(
        "pos.order",
        string="Documento Original",
        readonly=True,
    )

    sunat_origin_document_type = fields.Char(
        string="Tipo documento Original",
        readonly=True,
    )

    sunat_origin_document_number = fields.Char(
        string="Número documento Original",
        readonly=True,
    )

    sunat_credit_note_reason_code = fields.Selection(
        [
            ("01", "Anulación de la operación"),
            ("02", "Anulación por error en el RUC"),
            ("03", "Corrección por error en la descripción"),
            ("04", "Descuento global"),
            ("05", "Descuento por ítem"),
            ("06", "Devolución total"),
            ("07", "Devolución por ítem"),
            ("08", "Bonificación"),
            ("09", "Disminución en el valor"),
            ("10", "Otros conceptos de disminución en el valor"),
        ],
        string="Motivo Nota de crédito",
        readonly=True,
    )

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

    # =====================================================
    # DATOS DEL RC DE BAJA SUNAT
    # Se mantienen separados del RC original para no perder
    # el historial del documento que fue aceptado inicialmente.
    # =====================================================

    sunat_cancel_summary_id = fields.Char(
        string="Ticket RC de Baja",
        readonly=True,
    )

    sunat_cancel_rc_batch_id = fields.Many2one(
        "sunat.summary.batch",
        string="Lote RC de Baja",
        readonly=True,
    )

    sunat_cancel_message = fields.Text(
        string="Mensaje Baja SUNAT",
        readonly=True,
    )

    # =====================================================
    # CONTROL PARA MOSTRAR EL BOTÓN "PREPARAR BAJA SUNAT"
    # =====================================================
    # Este campo pertenece a pos_sunat_direct.
    # Evita usar directamente en el XML los campos
    # venta_anulada y es_reversa_anulacion, que pertenecen
    # al módulo pos_anulacion_ventas.
    sunat_can_prepare_cancel = fields.Boolean(
        string="Puede preparar baja SUNAT",
        compute="_compute_sunat_can_prepare_cancel",
    )

    def action_print_comprobante_a4_html(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/pos_ticket_textil/comprobante/a4/%s" % self.id,
            "target": "new",
        }

    def action_open_credit_note_wizard(self):
        self.ensure_one()

        if self.sunat_state != "aceptado":
            raise UserError(
                "Solo se puede crear Nota de Crédito de documentos aceptados por SUNAT."
            )

        if self.sunat_document_type not in ("01", "03"):
            raise UserError(
                "Solo se puede crear Nota de Crédito desde Factura o Boleta."
            )

        if not self.sunat_document_number:
            raise UserError("La orden no tiene número de documento SUNAT.")

        return {
            "type": "ir.actions.act_window",
            "name": "Crear Nota de Crédito SUNAT",
            "res_model": "sunat.credit.note.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
            },
        }

    def _compute_sunat_can_prepare_cancel(self):
        for order in self:
            # Estos campos pertenecen al módulo pos_anulacion_ventas.
            # Usamos getattr para que pos_sunat_direct no dependa
            # directamente de ese módulo.
            venta_anulada = getattr(order, "venta_anulada", False)
            es_reversa = getattr(order, "es_reversa_anulacion", False)

            # El botón "Preparar baja SUNAT" solo debe aparecer cuando:
            # - Sea una Boleta.
            # - Ya esté aceptada por SUNAT.
            # - Esté cancelada en Odoo o marcada como anulada.
            # - No sea una reversa de anulación.
            # - Todavía no tenga un RC de baja creado.
            order.sunat_can_prepare_cancel = (
                order.sunat_document_type == "03"
                and order.sunat_state == "aceptado"
                and (order.state == "cancel" or venta_anulada)
                and not es_reversa
                and not order.sunat_cancel_rc_batch_id
            )

    def action_create_sunat_cancel_rc(self):
        """
        Crea un Resumen Diario de baja SUNAT para una boleta
        que quedó anulada en Odoo pero ya fue aceptada por SUNAT.

        No envía automáticamente:
        crea el lote de baja para poder revisarlo antes del envío.
        """
        self.ensure_one()

        # =====================================================
        # VALIDACIONES DE SEGURIDAD
        # =====================================================

        if self.sunat_document_type != "03":
            raise UserError("La baja mediante Resumen Diario solo aplica a Boletas.")

        if not self.sunat_document_number:
            raise UserError("La orden no tiene número de Boleta SUNAT.")

        # La boleta debe haber sido aceptada previamente por SUNAT.
        if self.sunat_state != "aceptado":
            raise UserError(
                "Solo se puede comunicar la baja de una boleta "
                "que previamente fue aceptada por SUNAT."
            )

        # =====================================================
        # VALIDAR QUE EXISTA EL RC ORIGINAL ACEPTADO
        # =====================================================
        if not self.sunat_rc_batch_id:
            raise UserError(
                "La boleta figura como aceptada, pero no tiene "
                "un Resumen Diario original asociado."
            )

        if self.sunat_rc_batch_id.state != "accepted":
            raise UserError(
                "El Resumen Diario original de esta boleta "
                "no figura como aceptado por SUNAT."
            )

        # =====================================================
        # VALIDAR QUE LA ORDEN ESTÉ CANCELADA / ANULADA
        # =====================================================
        # Puede haber quedado cancelada directamente por Odoo
        # (state = cancel) o haber pasado por nuestro flujo
        # personalizado de anulación (venta_anulada = True).
        esta_cancelada = self.state == "cancel"
        esta_anulada = getattr(self, "venta_anulada", False)

        if not esta_cancelada and not esta_anulada:
            raise UserError(
                "Esta orden no está cancelada ni marcada como anulada en Odoo."
            )

        # Una reversa de anulación no debe generar una baja SUNAT.
        if getattr(self, "es_reversa_anulacion", False):
            raise UserError(
                "Una orden de reversa de anulación no puede generar una baja SUNAT."
            )

        # Evitar crear dos bajas para el mismo documento.
        if self.sunat_cancel_rc_batch_id:
            raise UserError("Esta boleta ya tiene un Resumen Diario de baja asociado.")

        # =====================================================
        # FECHA ORIGINAL DE LA BOLETA EN HORA PERÚ
        # =====================================================

        fecha_boleta = fields.Datetime.context_timestamp(
            self,
            self.date_order,
        ).date()

        # =====================================================
        # CREAR LOTE DE BAJA
        # =====================================================

        batch = self.env["sunat.summary.batch"].create(
            {
                "date": fecha_boleta,
                "summary_type": "cancel",
                "order_ids": [(6, 0, self.ids)],
            }
        )

        # Guardamos la relación desde este momento para impedir
        # crear accidentalmente otra baja para la misma boleta.
        self.write(
            {
                "sunat_cancel_rc_batch_id": batch.id,
                "sunat_cancel_message": (
                    f"RC de baja {batch.id} creado. " "Pendiente de envío a SUNAT."
                ),
            }
        )

        # Abrir el lote para revisarlo antes de enviarlo.
        return {
            "type": "ir.actions.act_window",
            "name": "Resumen Diario de Baja SUNAT",
            "res_model": "sunat.summary.batch",
            "res_id": batch.id,
            "view_mode": "form",
            "target": "current",
        }

    def _get_tipo_doc(self):
        self.ensure_one()
        if self.sunat_document_type:
            return self.sunat_document_type

        return "03"

    def _get_serie(self, tipo):
        self.ensure_one()
        cfg = self.session_id.config_id

        if tipo == "01":
            return cfg.sunat_serie_factura

        if tipo == "03":
            return cfg.sunat_serie_boleta

        if tipo == "07":
            if self.sunat_origin_document_type == "01":
                return cfg.sunat_serie_nota_credito_factura

            return cfg.sunat_serie_nota_credito

        if tipo == "NV":
            return cfg.sunat_serie_nota_venta

        raise UserError(f"Tipo de documento SUNAT no válido:%s" % tipo)

    # OJO:
    # esto luego lo cambiaremos por ir.sequence oficial SUNAT
    def _get_correlativo(self, tipo):
        self.ensure_one()

        cfg = self.session_id.config_id

        if tipo == "01":
            sequence = cfg.sunat_sequence_factura_id

        elif tipo == "03":
            sequence = cfg.sunat_sequence_boleta_id

        elif tipo == "07":
            if self.sunat_origin_document_type == "01":
                sequence = cfg.sunat_sequence_nota_credito_factura_id
            else:
                sequence = cfg.sunat_sequence_nota_credito_id

        elif tipo == "NV":
            sequence = cfg.sunat_sequence_nota_venta_id

        else:
            raise UserError(f"Tipo de documento SUNAT no válido:%s" % tipo)

        if not sequence:
            raise UserError(
                "Falta configurar la secuencia SUNAT en el punto de venta" % tipo
            )

        return sequence.next_by_id()

    def action_generate_sunat_xml(self):
        for order in self:
            try:
                tipo = order._get_tipo_doc()
                serie = order._get_serie(tipo)
                correlativo = order._get_correlativo(tipo)

                nombre_cpe = (
                    f"{order.company_id.vat}-" f"{tipo}-" f"{serie}-" f"{correlativo}"
                )

                if tipo == "07":
                    xml = SunatUBLBuilder.build_credit_note_xml(
                        order,
                        serie,
                        correlativo,
                    )
                else:
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

            # No reenviar documentos que ya fueron aceptados,
            # tienen una baja en proceso o ya fueron dados de baja.
            if order.sunat_state in (
                "aceptado",
                "baja_enviada",
                "baja_aceptada",
            ):
                order.write(
                    {
                        "sunat_message": (
                            "Documento ya fue procesado por SUNAT "
                            "o tiene una baja en proceso. No se reenviará."
                        )
                    }
                )
                continue

            send_attempted = False

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

                # Desde este punto sí hubo intento real de comunicación con SUNAT.
                send_attempted = True

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
                            "sunat_state": "pendiente_verificacion",
                            "sunat_message": (
                                "SUNAT respondió pero no se recibió un CDR. "
                                "Se verificará el estado del comprobante antes de reenviarlo.\n\n"
                                f"HTTP {status_code}\n{response_text[:3000]}"
                            ),
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
                if send_attempted:
                    # Ya se intentó comunicar con SUNAT.
                    # No sabemos si recibió el comprobante.
                    order.write(
                        {
                            "sunat_state": "pendiente_verificacion",
                            "sunat_message": (
                                "No se pudo confirmar la respuesta de SUNAT. "
                                "Se verificará el comprobante antes de intentar "
                                "reenviarlo.\n\n"
                                f"Error: {str(e)}"
                            ),
                        }
                    )
                else:
                    # El error ocurrió antes de intentar sendBill.
                    # SUNAT no fue contactado.
                    order.write(
                        {
                            "sunat_state": "error",
                            "sunat_message": (
                                "No se pudo preparar el comprobante para SUNAT. "
                                "No se realizará un reenvío automático hasta "
                                "corregir el problema.\n\n"
                                f"Error: {str(e)}"
                            ),
                        }
                    )

        return True

    def action_generate_summary_rc(self):
        raise UserError(
            "Este botón está deshabilitado. Las boletas deben enviarse únicamente "
            "desde Resúmenes RC SUNAT / cron de resumen diario."
        )

    def action_send_pending_to_sunat(self):

        pendientes = self.search([("sunat_state", "=", "pendiente_envio")])

        for order in pendientes:
            order.action_send_sunat()

        return True

    def action_verify_sunat_invoice(self):
        for order in self:

            if order.sunat_document_type != "01":
                continue

            if order.sunat_state != "pendiente_verificacion":
                continue

            if not order.sunat_document_number:
                order.write(
                    {
                        "sunat_message": (
                            "No se puede verificar en SUNAT porque "
                            "el comprobante no tiene número."
                        )
                    }
                )
                continue

            try:
                serie, correlativo = order.sunat_document_number.split("-", 1)

                # Para las consultas SUNAT usamos el correlativo numérico
                # sin ceros a la izquierda.
                correlativo_consulta = str(int(correlativo))

                cfg = order.session_id.config_id.sudo()

                # El servicio billConsultService corresponde a producción.
                # En modo BETA no debemos consultar ni decidir reenvíos
                # utilizando información del ambiente de producción.
                if cfg.sunat_mode == "beta":
                    order.write(
                        {
                            "sunat_message": (
                                "La factura está pendiente de verificación. "
                                "La consulta automática de CDR no se ejecuta "
                                "en modo BETA porque billConsultService "
                                "corresponde al ambiente de producción."
                            )
                        }
                    )
                    continue

                company_vat = order.company_id.vat
                username = f"{company_vat}{cfg.sunat_user}"

                status_code, response_text = SunatClient.get_status_cdr(
                    username,
                    cfg.sunat_password,
                    company_vat,
                    order.sunat_document_type,
                    serie,
                    correlativo_consulta,
                )

                cdr_base64 = SunatCDR.extract_content(response_text)

                if cdr_base64:
                    cdr = SunatCDR.parse_cdr(cdr_base64)

                    estado = "aceptado" if cdr["code"] == "0" else "observado"

                    order.write(
                        {
                            "sunat_state": estado,
                            "sunat_cdr_filename": (
                                f"R-{order.sunat_zip_filename}"
                                if order.sunat_zip_filename
                                else False
                            ),
                            "sunat_cdr_file": cdr_base64,
                            "sunat_cdr_code": cdr["code"],
                            "sunat_cdr_description": cdr["description"],
                            "sunat_message": (
                                "CDR recuperado mediante consulta SUNAT. "
                                f"Código={cdr['code']} | "
                                f"{cdr['description']}"
                            ),
                        }
                    )
                    continue

                # =====================================================
                # NO SE RECUPERÓ CDR: CONSULTAR SI EL DOCUMENTO EXISTE
                # =====================================================

                status_http, status_response = SunatClient.get_document_status(
                    username,
                    cfg.sunat_password,
                    company_vat,
                    order.sunat_document_type,
                    serie,
                    correlativo_consulta,
                )

                sunat_status = SunatCDR.extract_status(status_response)
                sunat_code = sunat_status["code"]
                sunat_status_message = sunat_status["message"]

                # -----------------------------------------------------
                # 0011: SUNAT confirma que el comprobante NO existe.
                # Recién aquí es seguro habilitar un nuevo envío.
                # -----------------------------------------------------
                if sunat_code == "0011":
                    order.write(
                        {
                            "sunat_state": "pendiente_envio",
                            "sunat_message": (
                                "SUNAT confirmó que el comprobante no existe. "
                                "Queda habilitado para reintento de envío.\n\n"
                                f"Código SUNAT: {sunat_code} - "
                                f"{sunat_status_message}"
                            ),
                        }
                    )
                    continue

                # -----------------------------------------------------
                # 0001: existe y está aceptado.
                # NO reenviar. Seguimos intentando recuperar el CDR.
                # -----------------------------------------------------
                if sunat_code == "0001":
                    order.write(
                        {
                            "sunat_message": (
                                "SUNAT confirmó que el comprobante existe "
                                "y está aceptado, pero todavía no se recuperó "
                                "el CDR. No se reenviará.\n\n"
                                f"Código SUNAT: {sunat_code} - "
                                f"{sunat_status_message}"
                            ),
                        }
                    )
                    continue

                # -----------------------------------------------------
                # 0002: existe pero fue rechazado.
                # No se debe reenviar el mismo comprobante.
                # -----------------------------------------------------
                if sunat_code == "0002":
                    order.write(
                        {
                            "sunat_state": "observado",
                            "sunat_message": (
                                "SUNAT confirmó que el comprobante fue rechazado. "
                                "No se realizará un reenvío automático.\n\n"
                                f"Código SUNAT: {sunat_code} - "
                                f"{sunat_status_message}"
                            ),
                        }
                    )
                    continue

                # -----------------------------------------------------
                # 0003: el comprobante existe pero está de baja.
                # -----------------------------------------------------
                if sunat_code == "0003":
                    order.write(
                        {
                            "sunat_state": "baja_aceptada",
                            "sunat_message": (
                                "SUNAT confirmó que el comprobante está de baja.\n\n"
                                f"Código SUNAT: {sunat_code} - "
                                f"{sunat_status_message}"
                            ),
                        }
                    )
                    continue

                # Cualquier otra respuesta NO autoriza un reenvío.
                order.write(
                    {
                        "sunat_message": (
                            "No fue posible confirmar de forma segura "
                            "el estado del comprobante. "
                            "Se mantendrá pendiente de verificación.\n\n"
                            f"HTTP {status_http}\n"
                            f"Código SUNAT: {sunat_code or 'sin código'}\n"
                            f"{sunat_status_message or status_response[:2000]}"
                        )
                    }
                )

            except Exception as e:
                order.write(
                    {
                        "sunat_message": (
                            "No se pudo verificar el comprobante en SUNAT. "
                            "Se mantendrá pendiente de verificación.\n\n"
                            f"Error: {str(e)}"
                        )
                    }
                )

        return True

    def _process_order(self, order, draft):
        pos_order_id = super()._process_order(order, draft)
        pos_order = self.browse(pos_order_id)

        # ============================================================
        # SEGURIDAD: NO GENERAR DOCUMENTOS EN ÓRDENES NO FINALIZADAS
        #
        # Una orden cancelada o que no llegó a completarse no debe:
        # - consumir correlativo
        # - generar XML
        # - quedar pendiente de resumen SUNAT
        # ============================================================
        if (
            not pos_order
            or not pos_order.exists()
            or pos_order.state not in ("paid", "done", "invoiced")
        ):
            return pos_order_id

        try:
            if pos_order and pos_order.exists():

                tipo = pos_order._get_tipo_doc()

                # NOTA DE VENTA(No se envia a SUNAT)
                if tipo == "NV":
                    cfg = pos_order.session_id.config_id
                    if not cfg.sunat_serie_nota_venta:
                        raise Exception(
                            "Falta configurar la serie para Nota de Venta en el punto de venta"
                        )

                    if not cfg.sunat_sequence_nota_venta_id:
                        raise Exception(
                            "Falta configurar la secuencia para Nota de Venta en el punto de venta"
                        )

                    correlativo = cfg.sunat_sequence_nota_venta_id.next_by_id()

                    pos_order.write(
                        {
                            "sunat_state": "nota_venta",
                            "sunat_document_type": "NV",
                            "sunat_document_number": f"{cfg.sunat_serie_nota_venta}-{correlativo}",
                            "sunat_message": "Nota de Venta - No se envía a SUNAT",
                        }
                    )
                    return pos_order_id

                # FACTURA (envío directo a SUNAT)
                elif tipo == "01":
                    if not pos_order.sunat_xml:
                        pos_order.action_generate_sunat_xml()

                    pos_order.action_send_sunat()

                # BOLETA (envío por Resumen Diario)
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
                        "sunat_state": "error",
                        "sunat_message": (
                            "Error preparando el documento SUNAT. "
                            "No se realizará un reenvío automático "
                            "hasta corregir el problema.\n\n"
                            f"Error: {str(e)}"
                        ),
                    }
                )

        return pos_order_id

    tipo_documento_reporte = fields.Selection(
        [
            ("factura", "Factura"),
            ("boleta", "Boleta"),
            ("nota_credito", "Nota de Crédito"),
            ("nota_venta", "Nota de Venta"),
        ],
        string="Tipo Documento",
        compute="_compute_tipo_documento_reporte",
        store=True,
    )

    numero_documento_reporte = fields.Char(
        string="Número Documento",
        compute="_compute_tipo_documento_reporte",
        store=True,
    )

    @api.depends(
        "sunat_document_type", "sunat_document_number", "name", "pos_reference"
    )
    def _compute_tipo_documento_reporte(self):
        for order in self:

            if order.sunat_document_type == "01":
                order.tipo_documento_reporte = "factura"
                order.numero_documento_reporte = (
                    order.sunat_document_number or order.name
                )

            elif order.sunat_document_type == "03":
                order.tipo_documento_reporte = "boleta"
                order.numero_documento_reporte = (
                    order.sunat_document_number or order.name
                )

            elif order.sunat_document_type == "07":
                order.tipo_documento_reporte = "nota_credito"
                order.numero_documento_reporte = (
                    order.sunat_document_number or order.name
                )

            elif order.sunat_document_type == "NV":
                order.tipo_documento_reporte = "nota_venta"
                # Si sunat_document_number aún no existe, forzamos la obtención de la serie/correlativo
                if order.sunat_document_number:
                    order.numero_documento_reporte = order.sunat_document_number
                else:
                    cfg = order.session_id.config_id
                    if cfg and cfg.sunat_serie_nota_venta:
                        # Para reportar la serie configurada si no se ha guardado el correlativo aún
                        order.numero_documento_reporte = (
                            order.sunat_document_number or order.name
                        )
                    else:
                        order.numero_documento_reporte = order.name

            else:
                order.tipo_documento_reporte = False
                order.numero_documento_reporte = order.pos_reference or order.name

    @api.model
    def _order_fields(self, ui_order):
        vals = super()._order_fields(ui_order)

        # Control seguro: solo aceptar valores validos
        tipo = ui_order.get("sunat_document_type")

        if tipo in ("01", "03", "07", "NV"):

            vals["sunat_document_type"] = tipo

        else:
            vals["sunat_document_type"] = "03"  # Default a Boleta

        return vals
