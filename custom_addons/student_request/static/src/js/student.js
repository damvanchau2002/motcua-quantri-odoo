odoo.define('student_request.student_list_button', function (require) {
    'use strict';

    const ListController = require('web.ListController');
    const viewRegistry = require('web.view_registry');

    const CustomListController = ListController.extend({
        renderButtons: function ($node) {
            this._super($node);
            if (this.$buttons) {
                const myButton = $('<button type="button" class="btn btn-primary o_my_button">Đồng bộ</button>');
                myButton.on('click', () => {
                    this.do_action({
                        type: 'ir.actions.server',
                        name: 'Đồng bộ',
                        tag: 'action_sync_cluster',
                        res_model: 'student.dormitory.area',
                        target: 'new',
                    });
                });
                this.$buttons.append(myButton);
            }
        },
    });

    viewRegistry.add('student_dormitory_area_list_custom', {
        controller: CustomListController,
    });
});
