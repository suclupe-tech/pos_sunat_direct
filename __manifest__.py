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
        "data/sequence_data.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": False,
}
