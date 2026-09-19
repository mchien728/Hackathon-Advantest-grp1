FROM unifiedserver.local/all/template-data-app:v22.04
WORKDIR /opt/nexus/OneAPI
COPY bin/. ./bin
# TODO(Phase 6): COPY the trained model file (Phase 1 output) into ./bin here
# TODO(Phase 6): add exposed_ports/mapped_ports for the Phase 5 Flask dashboard in SmarTest/app_descriptor.json
ENV ONEAPI_DEBUG 6
WORKDIR /opt/nexus/OneAPI/bin
CMD ["python3", "-u", "main.py"]
