/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useInputField } from "@web/views/fields/input_field_hook";

export class DynamicFormWidget extends Component {
    static template = "student_request.DynamicFormWidget";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.state = useState({
            formData: {},
            formFields: [],
        });

        onWillStart(async () => {
            await this.loadFormFields();
        });

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.record.data.service_id !== this.props.record.data.service_id) {
                await this.loadFormFields();
            }
        });
    }

    async loadFormFields() {
        const record = this.props.record;

        // Safety check
        if (!record || !record.data) {
            this.state.formFields = [];
            this.state.formData = {};
            return;
        }

        const serviceFormFields = record.data.service_form_field_ids;

        // Handle different Odoo data structures
        if (serviceFormFields) {
            let fieldRecords = [];

            // Check if it's an array of records
            if (Array.isArray(serviceFormFields)) {
                fieldRecords = serviceFormFields;
            } else if (serviceFormFields.records) {
                // RelationalField with records property
                fieldRecords = serviceFormFields.records;
            } else if (serviceFormFields.currentIds) {
                // Many2one/One2many with currentIds
                fieldRecords = serviceFormFields.currentIds.map(id =>
                    serviceFormFields.data.find(r => r.id === id)
                ).filter(Boolean);
            }

            this.state.formFields = fieldRecords.map(field => {
                const fieldData = field.data || field;
                return {
                    name: fieldData.name || '',
                    label: fieldData.label || '',
                    field_type: fieldData.field_type || 'char',
                    required: fieldData.required || false,
                    placeholder: fieldData.placeholder || '',
                    selection_options: fieldData.selection_options || '',
                    sequence: fieldData.sequence || 0,
                };
            }).sort((a, b) => a.sequence - b.sequence);
        } else {
            this.state.formFields = [];
        }

        // Parse existing JSON data
        const customData = record.data[this.props.name];
        if (customData) {
            try {
                this.state.formData = JSON.parse(customData);
            } catch (e) {
                this.state.formData = {};
            }
        } else {
            this.state.formData = {};
        }
    }

    onFieldChange(fieldName, event) {
        const value = this.getInputValue(event.target);
        this.state.formData[fieldName] = value;
        this.updateRecord();
    }

    getInputValue(input) {
        if (input.type === 'checkbox') {
            return input.checked;
        } else if (input.type === 'number') {
            return parseFloat(input.value) || 0;
        }
        return input.value;
    }

    updateRecord() {
        const jsonString = JSON.stringify(this.state.formData);
        this.props.record.update({ [this.props.name]: jsonString });
    }

    getFieldValue(fieldName) {
        return this.state.formData[fieldName] || '';
    }

    renderField(field) {
        const value = this.getFieldValue(field.name);
        const inputId = `field_${field.name}`;
        const isReadonly = this.props.readonly;

        switch (field.field_type) {
            case 'char':
                return this.renderCharField(field, value, inputId, isReadonly);
            case 'text':
                return this.renderTextField(field, value, inputId, isReadonly);
            case 'integer':
            case 'float':
                return this.renderNumberField(field, value, inputId, isReadonly);
            case 'date':
                return this.renderDateField(field, value, inputId, isReadonly);
            case 'datetime':
                return this.renderDatetimeField(field, value, inputId, isReadonly);
            case 'boolean':
                return this.renderBooleanField(field, value, inputId, isReadonly);
            case 'selection':
                return this.renderSelectionField(field, value, inputId, isReadonly);
            default:
                return this.renderCharField(field, value, inputId, isReadonly);
        }
    }

    renderCharField(field, value, inputId, isReadonly) {
        return {
            type: 'text',
            value: value,
            placeholder: field.placeholder || '',
            readonly: isReadonly,
        };
    }

    renderTextField(field, value, inputId, isReadonly) {
        return {
            type: 'textarea',
            value: value,
            placeholder: field.placeholder || '',
            readonly: isReadonly,
        };
    }

    renderNumberField(field, value, inputId, isReadonly) {
        return {
            type: 'number',
            value: value,
            placeholder: field.placeholder || '',
            readonly: isReadonly,
            step: field.field_type === 'float' ? '0.01' : '1',
        };
    }

    renderDateField(field, value, inputId, isReadonly) {
        return {
            type: 'date',
            value: value,
            readonly: isReadonly,
        };
    }

    renderDatetimeField(field, value, inputId, isReadonly) {
        return {
            type: 'datetime-local',
            value: value,
            readonly: isReadonly,
        };
    }

    renderBooleanField(field, value, inputId, isReadonly) {
        return {
            type: 'checkbox',
            checked: !!value,
            readonly: isReadonly,
        };
    }

    renderSelectionField(field, value, inputId, isReadonly) {
        let options = [];
        if (field.selection_options) {
            try {
                options = JSON.parse(field.selection_options);
            } catch (e) {
                options = [];
            }
        }
        return {
            type: 'select',
            value: value,
            options: options,
            readonly: isReadonly,
        };
    }
}

registry.category("fields").add("dynamic_form", DynamicFormWidget);
