{
    "name": "POS SUNAT Direct",
    "version": "1.0",
    "category": "Point of Sale",
    "summary": "Integración directa POS con SUNAT",
    "depends": ["point_of_sale"],
    "data": [
        "views/pos_config_views.xml",
        "views/pos_order_views.xml",
        "views/sunat_summary_batch_views.xml",
        "views/pos_order_report.xml",
        "data/sequence_data.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_sunat_direct/static/src/js/document_type_pos.js",
            "pos_sunat_direct/static/src/xml/document_type_pos.xml",
        ],
    },
    "installable": True,
    "application": False,
}
