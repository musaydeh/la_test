# -*- coding: utf-8 -*-
{
    'name': "Product Packaging Sales",

    'summary': """Product Packaging Sales""",

    'description': """
        Product Packaging Sales
    """,

    'author': "Yahia Saleh",
    'website': "yahiasaleh911@gmail.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/14.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Sales/Sales',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['sale_management', 'sale_stock'],

    # always loaded
    'data': [
        'views/stock_warehouse_views.xml',
        'views/stock_package_type_views.xml',
        'views/product_packaging_views.xml',
        'views/sale_order_views.xml'
    ]
}
