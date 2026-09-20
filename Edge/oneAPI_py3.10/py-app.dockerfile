FROM unifiedserver.local/all/template-data-app:v22.04
WORKDIR /opt/nexus/OneAPI
COPY bin/. ./bin
COPY start.sh .
RUN chmod +x start.sh
ENV ONEAPI_DEBUG 6
WORKDIR /opt/nexus/OneAPI/bin
CMD ["python3", "-u", "main.py"]
