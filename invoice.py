##############################################################################
#    
#    OpenERP, Open Source Management Solution
#    Copyright (C) 
#    2004-2010 Tiny SPRL (<http://tiny.be>). 
#    2009-2010 Veritos (http://veritos.nl).
#    2013 Solnet Solutions Limited (http://solnetsolutions.co.nz
#    All Rights Reserved
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
# Known Issues
#
# None
#
#
#
# Accounting decisions
#
# For a sale line that is for a service product, no COS entry will be created
#
 

from openerp.osv import osv, fields
import logging

class purchase_line_invoice(osv.osv_memory):
    _inherit = 'purchase.order.line_invoice'
    

    def build_line(self,cr, uid, a, line, context=None):
        try:
            a.id
            account_id = a.id
        except:
            account_id = a
            
        res = {
            'name':line.name, 
            'origin':line.order_id.name, 
            'account_id':account_id, 
            'price_unit':line.price_unit, 
            'quantity':line.product_qty, 
            'uos_id':line.product_uom.id, 
            'product_id':line.product_id.id or False, 
            'invoice_line_tax_id':[(6, 0, [x.id for x in line.taxes_id])], 
            'account_analytic_id':line.account_analytic_id and line.account_analytic_id.id or False}
        return res

    def makeInvoices(self, cr, uid, ids, context=None):

        """
             This is a straight copy & paste from the purchase module
             as the coding is wrong. when a PO has a type of invoice from order
             but is for a stock line it needs to go to the stock input account
             or when the goods are received there is no off-setting entry.
        """

        if context is None:
            context={}

        record_ids =  context.get('active_ids',[])
        if record_ids:
            res = False
            invoices = {}
            invoice_obj=self.pool.get('account.invoice')
            purchase_line_obj=self.pool.get('purchase.order.line')
            property_obj=self.pool.get('ir.property')
            account_fiscal_obj=self.pool.get('account.fiscal.position')
            invoice_line_obj=self.pool.get('account.invoice.line')
            account_jrnl_obj=self.pool.get('account.journal')

            def multiple_order_invoice_notes(orders):
                notes = ""
                for order in orders:
                    notes += "%s \n" % order.notes
                return notes



            def make_invoice_by_partner(partner, orders, lines_ids):
                """
                    create a new invoice for one supplier
                    @param partner : The object partner
                    @param orders : The set of orders to add in the invoice
                    @param lines : The list of line's id
                """
                name = orders and orders[0].name or ''
                journal_id = account_jrnl_obj.search(cr, uid, [('type', '=', 'purchase')], context=None)
                journal_id = journal_id and journal_id[0] or False
                a = partner.property_account_payable.id
                inv = {
                    'name': name,
                    'origin': name,
                    'type': 'in_invoice',
                    'journal_id':journal_id,
                    'reference' : partner.ref,
                    'account_id': a,
                    'partner_id': partner.id,
                    'invoice_line': [(6,0,lines_ids)],
                    'currency_id' : orders[0].pricelist_id.currency_id.id,
                    'comment': multiple_order_invoice_notes(orders),
                    'payment_term': orders[0].payment_term_id.id,
                    'fiscal_position': partner.property_account_position.id
                }
                inv_id = invoice_obj.create(cr, uid, inv)
                for order in orders:
                    order.write({'invoice_ids': [(4, inv_id)]})
                return inv_id

            for line in purchase_line_obj.browse(cr,uid,record_ids):
                if (not line.invoiced):
                    if not line.partner_id.id in invoices:
                        invoices[line.partner_id.id] = []
                    if line.product_id:
                        if line.product_id.product_tmpl_id.type == 'service':
                            a = line.product_id.property_account_expense.id
                            if not a:
                                a = line.product_id.categ_id.property_account_expense_categ.id    
                        else:
                            a = line.product_id.property_stock_account_input
                            if not a:
                                a = line.product_id.categ_id.property_stock_account_input_categ.id
                        if not a:
                            raise osv.except_osv(('Error!'),
                                    ('Define expense account for this product: "%s" (id:%d).') % \
                                            (line.product_id.name, line.product_id.id,))
                    else:
                        a = property_obj.get(cr, uid,
                                'property_account_expense_categ', 'product.category',
                                context=context).id
                    fpos = line.order_id.fiscal_position or False
                    a = account_fiscal_obj.map_account(cr, uid, fpos, a)
                    res = self.build_line(cr, uid, a, line, context=context)
                    inv_id = invoice_line_obj.create(cr, uid, res)
                    purchase_line_obj.write(cr, uid, [line.id], {'invoiced': True, 'invoice_lines': [(4, inv_id)]})
                    invoices[line.partner_id.id].append((line,inv_id))

            res = []
            for result in invoices.values():
                il = map(lambda x: x[1], result)
                orders = list(set(map(lambda x : x[0].order_id, result)))

                res.append(make_invoice_by_partner(orders[0].partner_id, orders, il))

        return {
            'domain': "[('id','in', ["+','.join(map(str,res))+"])]",
            'name': ('Supplier Invoices'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'account.invoice',
            'view_id': False,
            'context': "{'type':'in_invoice', 'journal_type': 'purchase'}",
            'type': 'ir.actions.act_window'
        }
purchase_line_invoice()



class account_invoice(osv.osv):
    _inherit = "account.invoice"

    _columns = {
        'picking_ids': fields.many2many('stock.picking', 'picking_invoice_rel', 'invoice_id', 'picking_id', 'Pickings' ),
        'sale_order_ids': fields.many2many('sale.order', 'sale_order_invoice_rel', 'invoice_id', 'order_id', 'Sale Orders', readonly = True, help = "This is the list of sale orders linked to this invoice."),
        "purchase_order_ids": fields.many2many ("purchase.order", "purchase_invoice_rel", "invoice_id", "purchase_id", "Purchase Orders", readonly = True, help = "This is the list of Purchase orders linked to this invoice.")
    }
    
    def copy(self, cr, uid, id, default=None, context=None):
        default = default or {}
        default.update({
            'picking_ids':[],
            'sale_order_ids':[],
            })
        return super(account_invoice, self).copy(cr, uid, id, default, context)
                            
    
    #def finalize_invoice_move_lines(self, cr, uid, invoice_browse, move_lines):
        


class account_invoice_line(osv.osv):
    _inherit = "account.invoice.line"
    
    def move_line_get_get_price(self, cr, uid, inv, company_currency,i_line):
        cur_obj = self.pool.get('res.currency')
        if i_line.cost_price:
            cost_price = i_line.cost_price
        else:
            cost_price = i_line.product_id.product_tmpl_id.standard_price
        if inv.currency_id.id != company_currency:
            price = cur_obj.compute(cr, uid, company_currency, inv.currency_id.id, cost_price * i_line.quantity, context={'date': inv.date_invoice})
        else:
            price = cost_price * i_line.quantity
        return price
    
    def is_invoice_line_on_sales_order(self, cr, invoice_line):
        """
        Check if the invoice line has a linked sale order line
        Return true if yes
        """
        invoice_line = invoice_line.id
        cr.execute("select order_line_id from sale_order_line_invoice_rel where invoice_id = %s",(invoice_line,))
        result = cr.fetchone()
        if result and len(result):
            return True
        else:
            return False

    def is_this_a_direct_delivery(self, cr, invoice_line):
        '''
        Check if invoice is for direct delivery.
        '''
        so_line_inv_rel = False
        direct_ship = False
        
        invoice_line = invoice_line.id
        cr.execute("select order_line_id from sale_order_line_invoice_rel where invoice_id = %s",(invoice_line,))
        result = cr.fetchone()
        if result and len(result):
            so_line_inv_rel = result[0]
            cr.execute("select procurement_id from sale_order_line where id = %s", (so_line_inv_rel,))
            procurement_id = cr.fetchone()
            if procurement_id and len(procurement_id):
                cr.execute("select move_id from procurement_order where id = %s", (procurement_id,))
                move_id = cr.fetchone()
                if move_id and len(move_id):
                    stock_move_id = result[0]
                    cr.execute("select order_id from purchase_order_line where move_dest_id = %s", (stock_move_id,))
                    po_id = cr.fetchone()
                    if po_id and len(po_id):
                        order_id = result[0]
                        cr.execute("select dest_address_id from purchase_order where id = %s", (order_id,))
                        addr_id = cr.fetchone()
                        if addr_id and len(addr_id):
                            direct_ship = True
        return direct_ship

    def is_invoice_line_not_for_a_service(self, invoice_line):
        return invoice_line.product_id and not invoice_line.product_id.product_tmpl_id.type == 'service'


    def determine_debit_account_for_non_service_invoice_line(self, invoice_line, direct_ship):
        '''
        Given an invoice line that is for a service product and a flag indicating whether the
        service is for direct delivery, this method returns the debit account to be used.
        '''
        dacc = False
        if direct_ship == True: # debit account dacc will be the output account
            # first check the product, if empty check the category
            dacc = invoice_line.product_id.product_tmpl_id.property_stock_account_input and invoice_line.product_id.product_tmpl_id.property_stock_account_input.id
            if not dacc:
                dacc = invoice_line.product_id.categ_id.property_stock_account_input_categ and invoice_line.product_id.categ_id.property_stock_account_input_categ.id
        else:
            dacc = invoice_line.product_id.product_tmpl_id.property_stock_account_output and invoice_line.product_id.product_tmpl_id.property_stock_account_output.id
            if not dacc:
                dacc = invoice_line.product_id.categ_id.property_stock_account_output_categ and invoice_line.product_id.categ_id.property_stock_account_output_categ.id
        return dacc


    def determine_credit_account_for_non_service_invoice_line(self, invoice_line):
        '''
        Given an invoice line that is for a service product this method returns a
        credit account to be used.
        
        In both cases the credit account cacc will be the expense account,
        first check the product, if empty check the category
        '''
        cacc = invoice_line.product_id.product_tmpl_id.property_account_expense and invoice_line.product_id.product_tmpl_id.property_account_expense.id
        if not cacc:
            cacc = invoice_line.product_id.categ_id.property_account_expense_categ and invoice_line.product_id.categ_id.property_account_expense_categ.id
        return cacc


    def add_move_lines_for_non_service_invoice_line(self, dictionary_of_account_move_lines, invoice_line, debit_account_id, credit_account_id, price):
        '''
        Adds account move lines for debit account and credit account for service invoice line.
        New account move lines are added to the dictionary of account move lines.
        '''
        dictionary_of_account_move_lines.append({'type':'src', 
                    'name':invoice_line.name[:64], 
                    'price_unit':invoice_line.product_id.product_tmpl_id.standard_price, 
                    'quantity':invoice_line.quantity, 
                    'price':price, 
                    'account_id':debit_account_id, 
                    'product_id':invoice_line.product_id.id, 
                    'uos_id':invoice_line.uos_id.id, 
                    'account_analytic_id':invoice_line.account_analytic_id.id, 
                    'account_analytic_id':False, 
                    'taxes':invoice_line.invoice_line_tax_id})
        
        dictionary_of_account_move_lines.append({'type':'src', 'name':invoice_line.name[:64], 
                    'price_unit':invoice_line.product_id.product_tmpl_id.standard_price, 
                    'quantity':invoice_line.quantity, 
                    'price':-1 * price, 
                    'account_id':credit_account_id, 
                    'product_id':invoice_line.product_id.id, 
                    'uos_id':invoice_line.uos_id.id, 
                    'account_analytic_id':invoice_line.account_analytic_id.id, 
                    'taxes':invoice_line.invoice_line_tax_id})
        
        return dictionary_of_account_move_lines
    

    def handle_invoices_of_out_invoice_or_out_refund_type_when_invoice_is_for_sales_order(self, cr, uid, dictionary_of_account_move_lines, inv, logger):
        '''
        This method handles creating account_move_lines for all invoices that have an invoice_type of 
        'out_invoice' or 'out_refund'
        '''
        
        logger.info('Handling invoices of with an invoice type of out_invoice or out_refund that are linked to a sales order.')
        company_currency = inv.company_id.currency_id.id
        for i_line in inv.invoice_line:
        #need to check if direct delivery
        #if so, then set dacc to stock input account as there will be no stock move journal
        #this entry will offset the input account entry created from the supplier invoice
        #TODO need to check what happens when the standard/average cost is <> buy price
        
        #also need to check if this product has been added just on the invoice
        #if so, then no COS entry
        
        #if this line is a service line then create no COS entries
            logger.debug('Processing invoice line with id: ' + `i_line.id`)
            if self.is_invoice_line_not_for_a_service(i_line):
                if self.is_invoice_line_on_sales_order(cr, i_line):
                    direct_ship = self.is_this_a_direct_delivery(cr, i_line)
                    dacc = self.determine_debit_account_for_non_service_invoice_line(i_line, direct_ship)
                    cacc = self.determine_credit_account_for_non_service_invoice_line(i_line)
                    if dacc and cacc:
                        price = self.move_line_get_get_price(cr, uid, inv, company_currency, i_line)
                        self.add_move_lines_for_non_service_invoice_line(dictionary_of_account_move_lines, i_line, dacc, cacc, price)
                    
        return dictionary_of_account_move_lines
    
        
    def group_invoice_lines_according_to_product(self, inv):
        '''
        This method groups invoice lines according to the product
        that they are for.  It returns a dictionary which has
        product ids as key and and invoice lines as values.
        '''
        product_set = set([inv_line.product_id.id for inv_line in inv.invoice_line])
        product_inv_line_map = {}
        for product_id in product_set:
            product_inv_line_map[product_id] = [inv_line for inv_line in inv.invoice_line if inv_line.product_id and inv_line.product_id.id == product_id]
        
        return product_inv_line_map


    def get_stock_moves_for_invoiced_product(self, cr, uid, inv, product, context):
        '''
        Obtains the stock pickings from invoice and checks whether there are any
        stock moves for those stock pickings pertaining to the product specified.
        
        The method returns any move_ids that are found (or empty list if none are found).
        Note added check where PO = Based on generated draft invoice or Based on Purchase Order Lines
        In this case need to find all moves that are in a state of done related to the PO
        as picking_invoice_rel is not updated where there is a back-order if the PO is as above
        
        Also need to check for return and deal with differently.
        '''
        move_obj = self.pool.get('stock.move')
        picking_obj=self.pool.get('stock.picking')
        purchase_obj=self.pool.get('purchase.order')
        location_obj=self.pool.get('stock.location')
        select_sql = 'select purchase_id from purchase_invoice_rel where invoice_id = %s'
        select_sql = select_sql % (inv.id)
        cr.execute(select_sql)
        purchase_orders = [x[0] for x in cr.fetchall()]
        for purchase_order in purchase_orders:
            invoice_method = purchase_obj.browse(cr, uid, purchase_order, context=context).invoice_method
            continue
        
        #TODO check SO methods
        if invoice_method in ('order','manual'):
            company=inv.company_id.id
            supplier_location_id = location_obj.search(cr, uid,[('company_id','=', company),('usage','=','supplier')])
            if not supplier_location_id:
                #TODO ideally should search based on company being null
                supplier_location_id = location_obj.search(cr, uid,[('usage','=','supplier')])
            if inv.type == 'in_refund':
                move_ids=[]
                picking_ids=[]
                picking_ids = picking_obj.search(cr, uid, [('purchase_id', '=', purchase_order )])
                move_ids = move_obj.search(cr, uid, [('picking_id', 'in', picking_ids), ('product_id', '=', product.id), ('state', '=', 'done'), ('location_dest_id','in', supplier_location_id )], 
                    context=context)
            else:
                move_ids=[]
                picking_ids=[]
                picking_ids = picking_obj.search(cr, uid, [('purchase_id', '=', purchase_order )])
                move_ids = move_obj.search(cr, uid, [('picking_id', 'in', picking_ids), ('product_id', '=', product.id), ('state', '=', 'done'), ('location_id','in', supplier_location_id )], 
                    context=context)
        else:
            move_ids = []
            picking_ids = [pk.id for pk in inv.picking_ids]
            if len(picking_ids):
                move_ids = move_obj.search(cr, uid, [('picking_id', 'in', picking_ids), ('product_id', '=', product.id), ('state', '=', 'done')], 
                    context=context)
        return move_ids


    def determine_price_difference_account_from_product_or_category(self, product):
        acc = product.product_tmpl_id.property_account_creditor_price_difference and product.product_tmpl_id.property_account_creditor_price_difference.id
        if not acc: # if not found on the product get the price difference account at the category
            acc = product.categ_id.property_account_creditor_price_difference_categ and product.categ_id.property_account_creditor_price_difference_categ.id
        return acc


    def for_in_determine_stock_input_account_from_product_or_category(self, product):
        # oa will be the stock input account irrespective if receipt or return
        # first check the product, if empty check the category   
        oa = product.product_tmpl_id.property_stock_account_input and product.product_tmpl_id.property_stock_account_input.id
        if not oa:
            oa = product.categ_id.property_stock_account_input_categ and product.categ_id.property_stock_account_input_categ.id
        return oa


    def determine_fiscal_position_account_from_stock_input_account(self, cr, uid, inv, stock_input_account):
        fpos_account = None
        if stock_input_account: # get the fiscal position
            fpos = inv.fiscal_position or False
            fpos_account = self.pool.get('account.fiscal.position').map_account(cr, uid, fpos, stock_input_account)
        return fpos_account


    def calculate_total_value_of_stock_moves(self, cr, uid, move_ids):
        move_value = 0.0
        move_obj = self.pool.get('stock.move')
        for move_line in move_obj.browse(cr, uid, move_ids): #TODO
            move_value += move_line.price_unit * move_line.product_qty
        
        return move_value


    def add_profit_and_loss_and_input_valuation_account_move_lines_for_price_difference(self, account_move_lines_for_price_difference, product_invoice_quantity, 
                                                                                        product, acc, fpos_account, account_analytic, price_diff):
        # P&L
        account_move_lines_for_price_difference.append({'type':'src', 
                                                        'name':product.name[:64], 
                                                        'price_unit':price_diff, 
                                                        'quantity':product_invoice_quantity, 
                                                        'price':price_diff, 
                                                        'account_id':acc, 
                                                        'product_id':product.id, 
                                                        'uos_id':product.uos_id.id, 
                                                        'account_analytic_id':account_analytic.id, 
                                                        'taxes':[]}) 
        
        # Input valuation
        account_move_lines_for_price_difference.append({'type':'src', 
                                                        'name':product.name[:64], 
                                                        'price_unit':price_diff, 
                                                        'quantity':product_invoice_quantity, 
                                                        'price':-price_diff, 
                                                        'account_id':fpos_account, 
                                                        'product_id':product.id, 
                                                        'uos_id':product.uos_id.id, 
                                                        'account_analytic_id':'', 
                                                        'taxes':[]})
        
        return account_move_lines_for_price_difference


    def handle_invoices_of_in_invoice_or_in_refund_when_invoice_is_for_purchase_order(self, cr, uid, inv, dict_account_move_lines, context, logger):
        '''
        this section rewritten to account for an invoice that has the same product in multiple lines eg a serialised product
        the standard logic did not support. this now groups by product in the invoice
        and compares that to the move lines value for the same product
        and creates a difference entry if required at the product level rather than the line level
        
        #changed to check if the in transaction is related to a PO
        #TO DO check that a refund of a PO related invoice keeps the relationship
        '''
        logger.info('Handling invoices of with an invoice type of in_invoice or in_refund that are linked to a purchase order.')
        product_inv_line_map = self.group_invoice_lines_according_to_product(inv)
        for product_id in product_inv_line_map.iterkeys():
            account_move_lines_for_price_difference = []
            move_line_value = 0
            product_invoice_quantity = 0
            product = self.pool.get('product.product').browse(cr, uid, product_id, context=context)
            invoice_lines_for_product = product_inv_line_map[product_id]
            for i_line in invoice_lines_for_product:
                move_line_value += i_line.price_unit * i_line.quantity
                product_invoice_quantity += i_line.quantity
            
            move_ids = self.get_stock_moves_for_invoiced_product(cr, uid, inv, product, context)
            if move_ids:
                move_value = self.calculate_total_value_of_stock_moves(cr, uid, move_ids)
                logger.info('move_value: %s' % move_value)
                price_diff = move_line_value - move_value
                logger.info('move_value diff: %s' % price_diff)
                acc = self.determine_price_difference_account_from_product_or_category(product)
                if price_diff and acc:
                    stock_input_account = self.for_in_determine_stock_input_account_from_product_or_category(product)
                    fpos_account = self.determine_fiscal_position_account_from_stock_input_account(cr, uid, inv, stock_input_account)
                    account_analytic = invoice_lines_for_product[0].account_analytic_id
                    self.add_profit_and_loss_and_input_valuation_account_move_lines_for_price_difference(account_move_lines_for_price_difference, 
                                                                                                         product_invoice_quantity, product, acc, 
                                                                                                         fpos_account, account_analytic, price_diff)
            dict_account_move_lines += account_move_lines_for_price_difference
        
        return dict_account_move_lines


    def check_if_invoice_is_for_sales_order(self, cr, invoice_id):
        so_inv_rel = False
        cr.execute("select invoice_id from sale_order_invoice_rel where invoice_id = %s", (invoice_id, ))
        result = cr.fetchone()
        if result:
            so_inv_rel = True
        return so_inv_rel


    def check_if_invoice_is_for_purchase_order(self, cr, invoice_id):
        po_inv_rel = False
        cr.execute("select invoice_id from purchase_invoice_rel where invoice_id = %s", (invoice_id, ))
        result = cr.fetchone()
        if result:
            po_inv_rel = True
        return po_inv_rel
    

    def move_line_get(self, cr, uid, invoice_id, context=None):
        '''
            #this now incorporates the fix for serialised products as per account_anglo_saxon_shipment_costing_patch
            #plus the fix identified by ferdinand at camp2camp
            #code now caters for
            # - an invoice (in or out) for a stockable product where there is no associated move
            # - direct ship of purchased products to a customer
        '''
        logger = logging.getLogger('account_anglo_saxon_solnet.move_line_get')
        dict_account_move_lines = super(account_invoice_line,self).move_line_get(cr, uid, invoice_id, context=context)
        inv = self.pool.get('account.invoice').browse(cr, uid, invoice_id, context=context)
        
        #this section below is changed from the original to cater for an invoice that has not been generated from a sales order
        #in this circumstance there is no output account entry to be offset to
        so_inv_rel = self.check_if_invoice_is_for_sales_order(cr, invoice_id)
        
        po_inv_rel = self.check_if_invoice_is_for_purchase_order(cr, invoice_id)
        
        if inv.type in ('out_invoice','out_refund') and so_inv_rel == True:
            self.handle_invoices_of_out_invoice_or_out_refund_type_when_invoice_is_for_sales_order(cr, uid, dict_account_move_lines, inv, logger)
        elif inv.type in ('in_invoice','in_refund') and po_inv_rel==True:
            self.handle_invoices_of_in_invoice_or_in_refund_when_invoice_is_for_purchase_order(cr, uid, inv, dict_account_move_lines, context, logger)
                
        return dict_account_move_lines
    
       
account_invoice_line()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
