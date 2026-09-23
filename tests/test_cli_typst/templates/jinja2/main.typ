{% for part in parts %}
{% for section in part.sections %}
{% if section is string %}
#include "{{ section }}.typ"
{% else %}
= {{ section.title }}
{% endif %}
{% endfor %}
{% endfor %}
