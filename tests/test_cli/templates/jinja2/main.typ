#set page(paper: "presentation-16-9")

#align(center + horizon)[
  #text(size: 2em)[{{ variables.deck_title }}]

  {{ variables.user_name }}

  #image("{{ variables.company_logo }}", height: {{ variables.company_logo_height }})

  #link("{{ variables.company_website }}")
]

#pagebreak()
#outline(title: [Program])

{% for part in parts %}
{% for item in part.sections %}
#pagebreak(weak: true)
{% if item is string %}
#include "{{ item }}.typ"
{% else %}
#heading(level: {{ item.level + 1 }})[{{ item.title }}]
{% endif %}
{% endfor %}
{% endfor %}
